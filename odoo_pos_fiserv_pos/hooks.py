# -*- coding: utf-8 -*-
"""
Hooks de instalación del módulo odoo_pos_fiserv_pos.

- ``pre_init_hook``: migra los ir.model.data del módulo antiguo ``odoo_pos_fiserv``
  hacia ``odoo_pos_fiserv_pos`` ANTES de cargar el XML nuevo (evita duplicados
  en pos.payment.method y en los reportes XML de ticket de cambio).
- ``post_init_hook``: garantiza el pos.payment.method Fiserv y su enlace al
  payment.provider Fiserv (creado por core).
"""

import logging

_logger = logging.getLogger(__name__)

_IRMD_NAMES_MIGRATED_TO_POS = (
    # Datos y reportes POS
    'pos_payment_method_fiserv',
    'fiserv_change_ticket_report',
    'action_report_pos_order_fiserv_change_ticket',
    # Vistas POS
    'pos_payment_method_form_fiserv',
    'pos_config_view_form_inherit_fiserv_change_ticket',
    'pos_payment_form_fiserv',
)


def pre_init_hook(env):
    """Reasigna los ir.model.data POS desde odoo_pos_fiserv → odoo_pos_fiserv_pos."""
    cr = env.cr
    try:
        cr.execute(
            "UPDATE ir_model_data SET module='odoo_pos_fiserv_pos' "
            "WHERE module='odoo_pos_fiserv' AND name = ANY(%s)",
            (list(_IRMD_NAMES_MIGRATED_TO_POS),),
        )
        _logger.info(
            "odoo_pos_fiserv_pos pre_init: %s ir.model.data reasignados desde odoo_pos_fiserv",
            cr.rowcount,
        )
    except Exception as exc:
        _logger.error("odoo_pos_fiserv_pos pre_init: %s", exc, exc_info=True)


def post_init_hook(env):
    try:
        _logger.info("Post-instalación odoo_pos_fiserv_pos: inicio")
        _ensure_fiserv_pos_payment_method(env)
        _link_pos_method_to_fiserv_provider(env)
        _logger.info("Post-instalación odoo_pos_fiserv_pos: completada")
    except Exception as exc:
        _logger.error("Post-instalación odoo_pos_fiserv_pos: error %s", exc, exc_info=True)


def _ensure_fiserv_pos_payment_method(env):
    try:
        pos_pm = env["pos.payment.method"].search(
            [("use_payment_terminal", "=", "fiserv")],
            limit=1,
        )
        if not pos_pm:
            receivable = env["account.account"].search(
                [
                    ("account_type", "=", "asset_receivable"),
                    ("company_id", "=", env.company.id),
                ],
                limit=1,
            )
            if not receivable:
                _logger.error("No hay cuenta por cobrar; no se crea método POS Fiserv")
                return
            provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
            vals = {
                "name": "Fiserv ITD",
                "use_payment_terminal": "fiserv",
                "receivable_account_id": receivable.id,
                "is_cash_count": False,
                "active": True,
                "sequence": 11,
                "url_webservice": "https://testitd.firstdata.com/v2/ITDService",
                "codigo_sistema": "1",
                "codigo_terminal": "001",
                "client_app_id": "1",
                "codigo_sucursal": 1,
            }
            if provider:
                vals["fiserv_provider_id"] = provider.id
            pos_pm = env["pos.payment.method"].create(vals)
            _logger.info("Método POS Fiserv creado en post_init")
        env["ir.model.data"]._update_xmlids([{
            "xml_id": "odoo_pos_fiserv_pos.pos_payment_method_fiserv",
            "record": pos_pm,
            "noupdate": True,
        }])
    except Exception as exc:
        _logger.error("_ensure_fiserv_pos_payment_method: %s", exc, exc_info=True)


def _link_pos_method_to_fiserv_provider(env):
    try:
        provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
        if not provider:
            return
        methods = env["pos.payment.method"].search(
            [
                ("use_payment_terminal", "=", "fiserv"),
                ("fiserv_provider_id", "=", False),
            ]
        )
        if methods:
            methods.write({"fiserv_provider_id": provider.id})
    except Exception as exc:
        _logger.error("_link_pos_method_to_fiserv_provider: %s", exc, exc_info=True)
