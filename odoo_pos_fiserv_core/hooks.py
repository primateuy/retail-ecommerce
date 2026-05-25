# -*- coding: utf-8 -*-
"""
Hooks de instalación del módulo odoo_pos_fiserv_core.

- ``pre_init_hook``: migra los ir.model.data del módulo antiguo ``odoo_pos_fiserv``
  hacia ``odoo_pos_fiserv_core`` ANTES de que el loader procese el XML nuevo.
  Sin esto, instalar core sobre una BD con el módulo viejo produce duplicados
  (violación de claves únicas en account.payment.method, payment.provider, etc.).
- ``post_init_hook``: completa proveedor, diario y método Card tras cargar el XML.
  Itera **todas las compañías** y aplica la misma lógica que la migración
  17.0.2.0.11, para que instalación fresca y update produzcan idéntico estado.

El helper ``_setup_fiserv_journal_for_company`` queda expuesto para que las
migraciones posteriores (>=17.0.2.0.16) lo reutilicen en vez de duplicar la
lógica de creación/normalización de diario y líneas Fiserv.
"""

import logging

_logger = logging.getLogger(__name__)

# Nombres de ir.model.data que antes pertenecían al módulo ``odoo_pos_fiserv`` y
# que la versión 17.0.2.0.0 publica en ``odoo_pos_fiserv_core``.
_IRMD_NAMES_MIGRATED_TO_CORE = (
    # Datos de instalación
    'payment_method_fiserv',
    'payment_provider_fiserv',
    'account_payment_method_fiserv',
    'account_journal_fiserv',
    'fiserv_default_config_url',
    'fiserv_default_config_timeout',
    'fiserv_default_config_retry_attempts',
    # Reporte voucher (modelo payment.transaction)
    'fiserv_card_voucher_snippet',
    'action_report_payment_transaction_fiserv_voucher',
    'payment_transaction_fiserv_voucher_report',
    # Seguridad
    'access_fiserv_pos_terminal_user',
    'access_fiserv_pos_terminal_manager',
    # Vistas y acciones de payment.provider / payment.transaction / terminal
    'payment_provider_form_fiserv',
    'view_payment_transaction_fiserv_form',
    'view_payment_transaction_fiserv_tree',
    'view_payment_transaction_fiserv_search',
    'action_payment_transaction_fiserv',
    'menu_payment_transaction_fiserv',
)


def pre_init_hook(env):
    """
    Reasigna al módulo nuevo los ``ir.model.data`` que cargó la versión anterior.

    Se ejecuta antes de procesar el XML de este módulo, evitando duplicados.
    """
    cr = env.cr
    try:
        cr.execute(
            "UPDATE ir_model_data SET module='odoo_pos_fiserv_core' "
            "WHERE module='odoo_pos_fiserv' AND name = ANY(%s)",
            (list(_IRMD_NAMES_MIGRATED_TO_CORE),),
        )
        _logger.info(
            "odoo_pos_fiserv_core pre_init: %s ir.model.data reasignados desde odoo_pos_fiserv",
            cr.rowcount,
        )
    except Exception as exc:
        _logger.error("odoo_pos_fiserv_core pre_init: %s", exc, exc_info=True)


def post_init_hook(env):
    """Completa datos que el XML deja incompletos o crea registros si faltan."""
    try:
        _logger.info("Post-instalación odoo_pos_fiserv_core: inicio")
        _ensure_fiserv_provider(env)
        _ensure_fiserv_journals_all_companies(env)
        _link_card_payment_method_to_fiserv(env)
        _logger.info("Post-instalación odoo_pos_fiserv_core: completada")
    except Exception as exc:
        _logger.error("Post-instalación odoo_pos_fiserv_core: error %s", exc, exc_info=True)


def _register_irmodel_data(env, xml_id_name, record):
    """Garantiza un ir.model.data para ``record`` con xml_id <core>.<name>."""
    try:
        env["ir.model.data"]._update_xmlids([{
            "xml_id": "odoo_pos_fiserv_core." + xml_id_name,
            "record": record,
            "noupdate": True,
        }])
    except Exception as exc:
        _logger.error("_register_irmodel_data(%s): %s", xml_id_name, exc, exc_info=True)


def _ensure_fiserv_provider(env):
    try:
        provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
        if not provider:
            payment_method = env["payment.method"].search([("code", "=", "fiserv")], limit=1)
            if not payment_method:
                _logger.warning("No existe payment.method fiserv; omito crear proveedor")
                return
            provider = env["payment.provider"].create(
                {
                    "name": "Fiserv ITD",
                    "code": "fiserv",
                    "state": "test",
                    "allow_tokenization": True,
                    "payment_method_ids": [(6, 0, [payment_method.id])],
                    "company_id": env.company.id,
                }
            )
            _logger.info("Proveedor Fiserv creado en post_init")
        _register_irmodel_data(env, "payment_provider_fiserv", provider)
    except Exception as exc:
        _logger.error("_ensure_fiserv_provider: %s", exc, exc_info=True)


def _patch_account_account_create_asset_default(cr):
    """
    Si ``account_account.create_asset`` es NOT NULL sin default, ponele ``'no'``.

    Necesario en BDs con ``account_asset`` enterprise: el INSERT interno que Odoo
    hace al crear un diario tipo bank no pasa este campo y rompe el create.
    Idempotente: no toca registros existentes, sólo evita rompimiento futuro.
    """
    cr.execute("""
        SELECT column_default, is_nullable
          FROM information_schema.columns
         WHERE table_name = 'account_account'
           AND column_name = 'create_asset'
    """)
    row = cr.fetchone()
    if not row:
        return
    column_default, is_nullable = row
    if column_default or is_nullable == 'YES':
        return
    cr.execute("""
        ALTER TABLE account_account
        ALTER COLUMN create_asset SET DEFAULT 'no'
    """)
    _logger.info(
        "Fiserv hooks: aplicado DEFAULT 'no' a account_account.create_asset"
    )


def _find_existing_fiserv_journal(env, company, provider, inbound_method):
    """
    Devuelve el diario que ya tenga una línea Fiserv inbound integrada (con
    ``payment_provider_id`` apuntando al provider Fiserv) en la compañía,
    sea cual sea su ``code``. Si no encuentra, devuelve un recordset vacío.

    Reutilizar el diario pre-existente evita violar
    ``_check_payment_method_line_ids_multiplicity`` (Odoo 17): para métodos
    electrónicos sólo puede existir UNA línea por
    (compañía, payment_method, payment_provider).
    """
    line = env['account.payment.method.line'].sudo().search([
        ('payment_method_id', '=', inbound_method.id),
        ('payment_provider_id', '=', provider.id),
        ('journal_id.company_id', '=', company.id),
    ], limit=1)
    return line.journal_id if line else env['account.journal'].sudo()


def _setup_fiserv_journal_for_company(env, company, provider, inbound_method,
                                       outbound_method, uyu):
    """
    Garantiza diario Fiserv + líneas inbound/outbound para una compañía.

    Estrategia (idéntica a la migración 17.0.2.0.11):
      1. Reutiliza el diario que ya tenga línea Fiserv integrada (cualquier code).
      2. Si no, busca por ``code='FSVR'``.
      3. Si tampoco, lo crea como tipo ``bank`` (moneda UYU si existe).
      4. Normaliza el ``code`` del diario a ``'FSVR'`` (decisión del cliente).
      5. Crea las líneas inbound y outbound si faltan, con
         ``payment_provider_id`` seteado.
      6. Rellena ``payment_provider_id`` en líneas Fiserv pre-existentes que
         hayan quedado vacías (residuo del bug histórico de 2.0.7).
      7. Registra ``odoo_pos_fiserv_core.account_journal_fiserv`` apuntando al
         diario resultante para que ``env.ref()`` funcione.

    Devuelve el ``account.journal`` configurado.
    """
    line_model = env['account.payment.method.line'].sudo()
    journal_model = env['account.journal'].sudo()

    # 1) Reutilizar diario Fiserv pre-existente (con cualquier code).
    journal = _find_existing_fiserv_journal(env, company, provider, inbound_method)

    # 2) Fallback al diario con code='FSVR'.
    if not journal:
        journal = journal_model.search(
            [('code', '=', 'FSVR'), ('company_id', '=', company.id)],
            limit=1,
        )

    # 3) Sigue sin haber: crear uno nuevo limpio.
    if not journal:
        journal_vals = {
            'name': 'Fiserv ITD',
            'code': 'FSVR',
            'type': 'bank',
            'company_id': company.id,
        }
        if uyu:
            journal_vals['currency_id'] = uyu.id
        journal = journal_model.create(journal_vals)
        _logger.info(
            "Fiserv setup: diario FSVR creado (compañía %s)", company.name,
        )

    # 4) Normalización pedida por el cliente: code uniforme 'FSVR'.
    if journal.code != 'FSVR':
        old_code = journal.code
        conflict = journal_model.search([
            ('code', '=', 'FSVR'),
            ('company_id', '=', company.id),
            ('id', '!=', journal.id),
        ], limit=1)
        if conflict:
            _logger.warning(
                "Fiserv setup: no normalizo code de diario %s -> 'FSVR' "
                "(compañía %s) porque ya existe otro diario FSVR (id=%s)",
                old_code, company.name, conflict.id,
            )
        else:
            journal.code = 'FSVR'
            _logger.info(
                "Fiserv setup: diario %s renombrado de '%s' a 'FSVR' (compañía %s)",
                journal.id, old_code, company.name,
            )

    # 5) Asegurar líneas inbound/outbound con payment_provider_id.
    for direction, account_pm in (
        ('inbound', inbound_method),
        ('outbound', outbound_method),
    ):
        if not account_pm:
            _logger.warning(
                "Fiserv setup: account.payment.method 'fiserv' %s no existe; salto",
                direction,
            )
            continue
        line = line_model.search([
            ('journal_id', '=', journal.id),
            ('payment_method_id', '=', account_pm.id),
        ], limit=1)
        if not line:
            line_model.create({
                'name': account_pm.name,
                'payment_method_id': account_pm.id,
                'journal_id': journal.id,
                'payment_provider_id': provider.id,
            })
            _logger.info(
                "Fiserv setup: línea %s creada en diario FSVR (compañía %s)",
                direction, company.name,
            )
        elif not line.payment_provider_id:
            line.payment_provider_id = provider.id
            _logger.info(
                "Fiserv setup: payment_provider_id seteado en línea %s (id=%s)",
                direction, line.id,
            )

    # 6) Registrar xml_id para que env.ref() funcione.
    _register_irmodel_data(env, 'account_journal_fiserv', journal)

    return journal


def setup_fiserv_journals_all_companies(env):
    """
    Punto de entrada compartido por ``post_init_hook`` y migraciones.

    Aplica el patch de ``account_account.create_asset`` y, por cada compañía,
    ejecuta ``_setup_fiserv_journal_for_company`` dentro de un savepoint para
    que un fallo en una compañía no aborte las demás.
    """
    _patch_account_account_create_asset_default(env.cr)

    provider = env['payment.provider'].sudo().search(
        [('code', '=', 'fiserv')], limit=1,
    )
    if not provider:
        _logger.info(
            "Fiserv setup: no hay payment.provider Fiserv; nada que configurar"
        )
        return

    inbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'inbound')], limit=1,
    )
    outbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'outbound')], limit=1,
    )
    if not inbound_method:
        _logger.warning(
            "Fiserv setup: account.payment.method 'fiserv' inbound no existe; "
            "abortando configuración de diarios"
        )
        return

    uyu = env.ref('base.UYU', raise_if_not_found=False)

    for company in env['res.company'].sudo().search([]):
        env.cr.execute("SAVEPOINT fiserv_setup_company")
        try:
            _setup_fiserv_journal_for_company(
                env, company, provider, inbound_method, outbound_method, uyu,
            )
            env.cr.execute("RELEASE SAVEPOINT fiserv_setup_company")
        except Exception as exc:
            env.cr.execute("ROLLBACK TO SAVEPOINT fiserv_setup_company")
            _logger.warning(
                "Fiserv setup (compañía %s): %s", company.name, exc,
            )


def _ensure_fiserv_journals_all_companies(env):
    """Wrapper interno del hook con try/except defensivo."""
    try:
        setup_fiserv_journals_all_companies(env)
    except Exception as exc:
        _logger.error(
            "_ensure_fiserv_journals_all_companies: %s", exc, exc_info=True,
        )


def _link_card_payment_method_to_fiserv(env):
    try:
        fiserv_provider = env["payment.provider"].search(
            [("code", "=", "fiserv")],
            limit=1,
        )
        if not fiserv_provider:
            return
        card_pm = env["payment.method"].search([("code", "=", "card")], limit=1)
        if not card_pm or card_pm in fiserv_provider.payment_method_ids:
            return
        fiserv_provider.payment_method_ids = [(4, card_pm.id)]
        _logger.info("Método Card vinculado al proveedor Fiserv")
    except Exception as exc:
        _logger.error("_link_card_payment_method_to_fiserv: %s", exc, exc_info=True)
