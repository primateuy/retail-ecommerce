# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.0 — División de odoo_pos_fiserv en tres módulos.

Renombra los registros ``ir.model.data`` de ``odoo_pos_fiserv`` hacia
``odoo_pos_fiserv_core`` o ``odoo_pos_fiserv_pos`` según corresponda. Así los
datos cargados por la versión anterior (provider Fiserv con credenciales reales,
diario FSVR, reportes, ACLs, ir.config_parameter) no se duplican ni se pierden
al instalar los módulos nuevos.

Referencias externas (p. ej. módulo puente odoo_pos_fiserv_pos_payment) siguen
resolviendo porque el meta-módulo depende de los tres hijos.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Ejecutado por el framework antes de cargar datos del nuevo módulo."""
    if not version:
        return
    _logger.info("odoo_pos_fiserv: migración 17.0.2.0.0 — renombrando ir.model.data")

    moves_core = [
        'payment_method_fiserv',
        'payment_provider_fiserv',
        'account_payment_method_fiserv',
        'account_journal_fiserv',
        'fiserv_default_config_url',
        'fiserv_default_config_timeout',
        'fiserv_default_config_retry_attempts',
        'fiserv_card_voucher_snippet',
        'action_report_payment_transaction_fiserv_voucher',
        'payment_transaction_fiserv_voucher_report',
        'access_fiserv_pos_terminal_user',
        'access_fiserv_pos_terminal_manager',
    ]
    moves_pos = [
        'pos_payment_method_fiserv',
        'fiserv_change_ticket_report',
        'action_report_pos_order_fiserv_change_ticket',
    ]

    cr.execute(
        "UPDATE ir_model_data SET module='odoo_pos_fiserv_core' "
        "WHERE module='odoo_pos_fiserv' AND name = ANY(%s)",
        (moves_core,),
    )
    _logger.info(
        "ir.model.data movidos a odoo_pos_fiserv_core: %s filas",
        cr.rowcount,
    )

    cr.execute(
        "UPDATE ir_model_data SET module='odoo_pos_fiserv_pos' "
        "WHERE module='odoo_pos_fiserv' AND name = ANY(%s)",
        (moves_pos,),
    )
    _logger.info(
        "ir.model.data movidos a odoo_pos_fiserv_pos: %s filas",
        cr.rowcount,
    )
