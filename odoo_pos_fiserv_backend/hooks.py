# -*- coding: utf-8 -*-
"""
Hooks de instalación del módulo odoo_pos_fiserv_backend.

Reasigna los ir.model.data de vistas que antes estaban declaradas en
``odoo_pos_fiserv`` (vistas del form de account.payment y del wizard
account.payment.register) para evitar que Odoo las borre y recrée al
instalar el módulo nuevo sobre una BD con el módulo viejo.
"""

import logging

_logger = logging.getLogger(__name__)

_IRMD_NAMES_MIGRATED_TO_BACKEND = (
    'account_payment_form_fiserv_terminal',
    'view_account_payment_register_form_fiserv',
)


def pre_init_hook(env):
    cr = env.cr
    try:
        cr.execute(
            "UPDATE ir_model_data SET module='odoo_pos_fiserv_backend' "
            "WHERE module='odoo_pos_fiserv' AND name = ANY(%s)",
            (list(_IRMD_NAMES_MIGRATED_TO_BACKEND),),
        )
        _logger.info(
            "odoo_pos_fiserv_backend pre_init: %s ir.model.data reasignados desde odoo_pos_fiserv",
            cr.rowcount,
        )
    except Exception as exc:
        _logger.error("odoo_pos_fiserv_backend pre_init: %s", exc, exc_info=True)
