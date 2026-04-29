# -*- coding: utf-8 -*-
"""
Hooks de instalación del módulo odoo_pos_fiserv_core.

- ``pre_init_hook``: migra los ir.model.data del módulo antiguo ``odoo_pos_fiserv``
  hacia ``odoo_pos_fiserv_core`` ANTES de que el loader procese el XML nuevo.
  Sin esto, instalar core sobre una BD con el módulo viejo produce duplicados
  (violación de claves únicas en account.payment.method, payment.provider, etc.).
- ``post_init_hook``: completa proveedor, diario y método Card tras cargar el XML.
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
        _ensure_fiserv_journal(env)
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


def _ensure_fiserv_journal(env):
    """
    Garantiza el diario Fiserv (code FSVR) y que tenga líneas de método de pago
    inbound/outbound asociadas al ``account.payment.method`` Fiserv.

    En Odoo 17 las líneas se manejan vía ``inbound_payment_method_line_ids`` /
    ``outbound_payment_method_line_ids`` (modelo ``account.payment.method.line``).
    """
    try:
        journal = env["account.journal"].search(
            [("code", "=", "FSVR"), ("company_id", "=", env.company.id)],
            limit=1,
        )
        account_pm = env["account.payment.method"].search(
            [("code", "=", "fiserv"), ("payment_type", "=", "inbound")],
            limit=1,
        )
        account_pm_out = env["account.payment.method"].search(
            [("code", "=", "fiserv"), ("payment_type", "=", "outbound")],
            limit=1,
        )
        if not account_pm:
            _logger.warning("No existe account.payment.method fiserv inbound")
            return
        if not journal:
            # Crear el diario bancario Fiserv FSVR.
            # Antes se omitía esta creación por temor a colisiones con módulos
            # Enterprise (activos), pero la versión meta vieja sí lo creaba sin
            # problemas. Sin journal, las account.payment.method.line nunca se
            # crean y el form de account.payment no muestra el método saliente
            # Fiserv → falla "Crear transacción" con UserError de proveedor.
            uyu = env.ref("base.UYU", raise_if_not_found=False)
            journal_vals = {
                "name": "Fiserv ITD",
                "code": "FSVR",
                "type": "bank",
                "company_id": env.company.id,
            }
            if uyu:
                journal_vals["currency_id"] = uyu.id
            journal = env["account.journal"].create(journal_vals)
            _logger.info("Diario Fiserv FSVR creado en post_init")
        provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
        _ensure_journal_payment_method_line(env, journal, account_pm, "inbound", provider)
        if account_pm_out:
            _ensure_journal_payment_method_line(env, journal, account_pm_out, "outbound", provider)
        _register_irmodel_data(env, "account_journal_fiserv", journal)
    except Exception as exc:
        _logger.error("_ensure_fiserv_journal: %s", exc, exc_info=True)


def _ensure_journal_payment_method_line(env, journal, account_pm, direction, provider=None):
    """
    Crea (si falta) una account.payment.method.line para el diario y el
    account.payment.method indicado. ``direction`` = 'inbound' o 'outbound'.

    Si se pasa ``provider`` (payment.provider Fiserv), se asegura que la línea
    tenga ``payment_provider_id`` apuntando a él. Sin proveedor en la línea
    saliente, el form de account.payment outbound no resuelve la integración
    con Fiserv ITD y «Crear transacción» falla.
    """
    line_model = env["account.payment.method.line"]
    domain = [
        ("journal_id", "=", journal.id),
        ("payment_method_id", "=", account_pm.id),
    ]
    existing = line_model.search(domain, limit=1)
    if existing:
        if provider and not existing.payment_provider_id:
            existing.payment_provider_id = provider.id
        return existing
    vals = {
        "name": account_pm.name,
        "payment_method_id": account_pm.id,
        "journal_id": journal.id,
    }
    if provider:
        vals["payment_provider_id"] = provider.id
    return line_model.create(vals)


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
