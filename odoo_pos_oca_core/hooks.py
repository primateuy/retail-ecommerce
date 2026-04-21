# -*- coding: utf-8 -*-
"""
Hooks de instalación del módulo odoo_pos_oca_core.

- ``pre_init_hook``: migra los ir.model.data del módulo antiguo ``odoo_pos_oca``
  hacia ``odoo_pos_oca_core`` ANTES de que el loader procese el XML nuevo.
  Sin esto, instalar core sobre una BD con el módulo viejo produce duplicados
  (violación de claves únicas en account.payment.method, payment.provider, etc.).
- ``post_init_hook``: completa proveedor, diario y método Card tras cargar el XML.
"""

import logging

_logger = logging.getLogger(__name__)

# Nombres de ir.model.data que antes pertenecían al módulo ``odoo_pos_oca`` y
# que ahora publica ``odoo_pos_oca_core``.
_IRMD_NAMES_MIGRATED_TO_CORE = (
    # Datos de instalación
    'payment_method_oca',
    'payment_provider_oca',
    'account_payment_method_oca',
    'account_journal_oca',
    'oca_default_config_url',
    'oca_default_config_timeout',
    'oca_default_config_retry_attempts',
    # Reporte voucher (modelo payment.transaction)
    'oca_card_voucher_snippet',
    'action_report_payment_transaction_oca_voucher',
    'payment_transaction_oca_voucher_report',
    # Seguridad
    'access_multiple_pos_config_user',
    'access_multiple_pos_config_manager',
    # Vistas y acciones de payment.provider / payment.transaction / terminal
    'payment_provider_form_oca',
    'view_payment_transaction_oca_form',
    'view_payment_transaction_oca_tree',
    'view_payment_transaction_oca_search',
    'action_payment_transaction_oca',
    'menu_payment_transaction_oca',
)


def pre_init_hook(env):
    """
    Tareas previas a cargar el XML del core:

    1. Reasigna al core los ``ir.model.data`` que cargó una versión anterior del
       stack OCA (monolito ``odoo_pos_oca`` o split intermedio
       ``odoo_pos_oca_backend``).
    2. **Deduplica** ``account.payment.method.line`` del method OCA. Odoo
       Enterprise tiene un constraint que impide que un mismo
       ``account.payment.method`` esté en líneas de varios diarios; el flush
       posterior a cargar el XML lo dispara antes de llegar al post_init. Por
       eso la limpieza se hace aquí.
    """
    cr = env.cr
    for source in ('odoo_pos_oca', 'odoo_pos_oca_backend'):
        try:
            cr.execute(
                "UPDATE ir_model_data SET module='odoo_pos_oca_core' "
                "WHERE module=%s AND name = ANY(%s)",
                (source, list(_IRMD_NAMES_MIGRATED_TO_CORE)),
            )
            if cr.rowcount:
                _logger.info(
                    "odoo_pos_oca_core pre_init: %s ir.model.data reasignados desde %s",
                    cr.rowcount, source,
                )
        except Exception as exc:
            _logger.error(
                "odoo_pos_oca_core pre_init (%s): %s", source, exc, exc_info=True,
            )

    # Deduplicación de líneas de método OCA antes del flush.
    try:
        _dedup_oca_payment_method_lines(env)
    except Exception as exc:
        _logger.error(
            "odoo_pos_oca_core pre_init dedup: %s", exc, exc_info=True,
        )


def _dedup_oca_payment_method_lines(env):
    """
    Deja solo una ``account.payment.method.line`` por (method, company) para
    los métodos con ``code='oca'``.

    Preferencia de journal para la línea sobreviviente:
    1. code='OCA' (histórico del monolito).
    2. code='OCAPOS'.
    3. El primer journal encontrado.
    """
    line_model = env["account.payment.method.line"].sudo()
    methods = env["account.payment.method"].sudo().search([("code", "=", "oca")])
    if not methods:
        return
    companies = env["res.company"].sudo().search([])
    for company in companies:
        for method in methods:
            lines = line_model.search([
                ("payment_method_id", "=", method.id),
                ("journal_id.company_id", "=", company.id),
            ])
            if len(lines) <= 1:
                continue
            # Escoger el journal preferido.
            preferred = lines.journal_id.filtered(lambda j: j.code == "OCA")
            if not preferred:
                preferred = lines.journal_id.filtered(lambda j: j.code == "OCAPOS")
            if not preferred:
                preferred = lines.journal_id[:1]
            keep_journal = preferred[0]
            to_keep = lines.filtered(lambda l: l.journal_id == keep_journal)[:1]
            duplicates = lines - to_keep
            _logger.warning(
                "OCA dedup: method=%s company=%s: %s líneas duplicadas en diarios "
                "%s, conservando %s.",
                method.code, company.name, len(duplicates),
                duplicates.mapped("journal_id.code"),
                keep_journal.code,
            )
            # Odoo bloquea unlink de una line cuyo payment_method esté enlazado
            # a un provider enabled/test; desactivamos el provider
            # temporalmente, borramos, restauramos el estado original.
            providers = env["payment.provider"].sudo().search(
                [("code", "=", "oca"), ("state", "in", ("enabled", "test"))]
            )
            previous_states = {p.id: p.state for p in providers}
            if providers:
                providers.write({"state": "disabled"})
            try:
                duplicates.unlink()
            finally:
                for prov in providers:
                    prov.state = previous_states.get(prov.id, "test")


def post_init_hook(env):
    """Completa datos que el XML deja incompletos o crea registros si faltan."""
    try:
        _logger.info("Post-instalación odoo_pos_oca_core: inicio")
        _ensure_oca_provider(env)
        _ensure_oca_journal(env)
        _link_card_payment_method_to_oca(env)
        _logger.info("Post-instalación odoo_pos_oca_core: completada")
    except Exception as exc:
        _logger.error("Post-instalación odoo_pos_oca_core: error %s", exc, exc_info=True)


def _register_irmodel_data(env, xml_id_name, record):
    """Garantiza un ir.model.data para ``record`` con xml_id <core>.<name>."""
    try:
        env["ir.model.data"]._update_xmlids([{
            "xml_id": "odoo_pos_oca_core." + xml_id_name,
            "record": record,
            "noupdate": True,
        }])
    except Exception as exc:
        _logger.error("_register_irmodel_data(%s): %s", xml_id_name, exc, exc_info=True)


def _ensure_oca_provider(env):
    try:
        provider = env["payment.provider"].search([("code", "=", "oca")], limit=1)
        if not provider:
            payment_method = env["payment.method"].search([("code", "=", "oca")], limit=1)
            if not payment_method:
                _logger.warning("No existe payment.method oca; omito crear proveedor")
                return
            provider = env["payment.provider"].create(
                {
                    "name": "OCA POSLink",
                    "code": "oca",
                    "state": "test",
                    "allow_tokenization": True,
                    "payment_method_ids": [(6, 0, [payment_method.id])],
                    "company_id": env.company.id,
                }
            )
            _logger.info("Proveedor OCA creado en post_init")
        _register_irmodel_data(env, "payment_provider_oca", provider)
    except Exception as exc:
        _logger.error("_ensure_oca_provider: %s", exc, exc_info=True)


def _ensure_oca_journal(env):
    """
    Garantiza un único diario OCA con línea ``account.payment.method.line``.

    Odoo Enterprise tiene un validador que impide que un mismo
    ``account.payment.method`` esté en líneas de varios diarios (contraint
    ``_check_payment_method_line_ids_multiplicity``). Este hook:

    1. Si ya hay una o más líneas con method OCA, usa el journal de la PRIMERA
       y elimina las demás (deduplica lo que dejaron instalaciones previas con
       dos diarios: el viejo ``OCA`` y el nuevo ``OCAPOS``).
    2. Si no hay ninguna línea, busca journal por code (``OCAPOS``, luego
       ``OCA``); crea uno nuevo ``OCAPOS`` si ninguno existe.
    3. Crea las líneas inbound/outbound faltantes sobre ese único journal.
    4. Registra ir.model.data ``account_journal_oca``.
    """
    try:
        account_pm = env["account.payment.method"].search(
            [("code", "=", "oca"), ("payment_type", "=", "inbound")],
            limit=1,
        )
        account_pm_out = env["account.payment.method"].search(
            [("code", "=", "oca"), ("payment_type", "=", "outbound")],
            limit=1,
        )
        if not account_pm:
            _logger.warning("No existe account.payment.method oca inbound")
            return

        # Paso 1: líneas existentes por method (en toda la compañía).
        existing_lines = env["account.payment.method.line"].search(
            [
                ("payment_method_id", "in", [
                    account_pm.id,
                    account_pm_out.id if account_pm_out else 0,
                ]),
                ("journal_id.company_id", "=", env.company.id),
            ],
        )
        journal = False
        if existing_lines:
            journals_with_lines = existing_lines.mapped("journal_id")
            # Preferir un journal con code='OCA' (histórico) si existe, si no el primero.
            preferred = journals_with_lines.filtered(lambda j: j.code == "OCA")
            journal = preferred[:1] or journals_with_lines[:1]
            journal = journal[0]
            duplicates = existing_lines.filtered(lambda l: l.journal_id != journal)
            if duplicates:
                _logger.warning(
                    "OCA: encontradas %s líneas OCA duplicadas en otros diarios (%s). "
                    "Dedup: dejo solo las del diario %s.",
                    len(duplicates),
                    duplicates.mapped("journal_id.code"),
                    journal.code,
                )
                duplicates.unlink()

        # Paso 2: si no hay líneas, buscar journal por code.
        if not journal:
            journal = env["account.journal"].search(
                [("code", "=", "OCAPOS"), ("company_id", "=", env.company.id)],
                limit=1,
            )
        if not journal:
            journal = env["account.journal"].search(
                [("code", "=", "OCA"), ("company_id", "=", env.company.id)],
                limit=1,
            )
        if not journal:
            # No creamos journal automáticamente para evitar bloqueos por
            # módulos Enterprise (activos) en compañías no principales.
            _logger.info(
                "OCA: no existe journal en compañía %s; skip (crear manual).",
                env.company.name,
            )
            return

        _ensure_journal_payment_method_line(env, journal, account_pm, "inbound")
        if account_pm_out:
            _ensure_journal_payment_method_line(env, journal, account_pm_out, "outbound")
        _register_irmodel_data(env, "account_journal_oca", journal)
    except Exception as exc:
        _logger.error("_ensure_oca_journal: %s", exc, exc_info=True)


def _ensure_journal_payment_method_line(env, journal, account_pm, direction):
    """
    Crea (si falta) una account.payment.method.line para el diario y el
    account.payment.method indicado. ``direction`` = 'inbound' o 'outbound'.
    """
    line_model = env["account.payment.method.line"]
    domain = [
        ("journal_id", "=", journal.id),
        ("payment_method_id", "=", account_pm.id),
    ]
    existing = line_model.search(domain, limit=1)
    if existing:
        return existing
    return line_model.create({
        "name": account_pm.name,
        "payment_method_id": account_pm.id,
        "journal_id": journal.id,
    })


def _link_card_payment_method_to_oca(env):
    try:
        oca_provider = env["payment.provider"].search(
            [("code", "=", "oca")],
            limit=1,
        )
        if not oca_provider:
            return
        card_pm = env["payment.method"].search([("code", "=", "card")], limit=1)
        if not card_pm or card_pm in oca_provider.payment_method_ids:
            return
        oca_provider.payment_method_ids = [(4, card_pm.id)]
        _logger.info("Método Card vinculado al proveedor OCA")
    except Exception as exc:
        _logger.error("_link_card_payment_method_to_oca: %s", exc, exc_info=True)
