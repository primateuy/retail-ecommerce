# -*- coding: utf-8 -*-
"""
Migración 17.0.1.0.3: desactiva bindings de server actions duplicadas en el
menú Acciones del tree de facturas:
    - ``odoo_pos_fiserv_backend.action_server_fiserv_register_payment``
      (duplicada cuando ambos backends coexisten).
    - ``account.action_account_invoice_from_list`` (nativa Odoo, abre el
      wizard estándar; nuestro flujo la reemplaza con un botón que abre el
      form de pago directamente).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    env = Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
        'odoo_pos_fiserv_backend.action_server_fiserv_register_payment',
        'account.action_account_invoice_from_list',
    ):
        try:
            action = env.ref(xmlid, raise_if_not_found=False)
            if action and action.binding_model_id:
                action.binding_model_id = False
                _logger.info(
                    "OCA backend 17.0.1.0.3: quitado binding de '%s'", xmlid,
                )
        except Exception as exc:
            _logger.warning("OCA backend 17.0.1.0.3 (%s): %s", xmlid, exc)
