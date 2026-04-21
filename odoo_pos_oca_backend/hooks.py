# -*- coding: utf-8 -*-
"""
Hooks del módulo odoo_pos_oca_backend.

Cuando Fiserv backend también está instalado en la misma BD, ambos módulos
añaden un botón «Registrar pago» equivalente en account.move y una
``ir.actions.server`` con binding al tree de facturas. El botón del form se
oculta vía compute (``pos_register_hide_fiserv``); la server action no tiene
campo ``active`` en Odoo 17, así que se quita del menú borrando su
``binding_model_id``.
"""

import logging

_logger = logging.getLogger(__name__)


def _hide_fiserv_register_server_action(env):
    action = env.ref(
        'odoo_pos_fiserv_backend.action_server_fiserv_register_payment',
        raise_if_not_found=False,
    )
    if action and action.binding_model_id:
        action.binding_model_id = False
        _logger.info(
            "OCA backend: quitado binding_model_id de la server action "
            "'odoo_pos_fiserv_backend.action_server_fiserv_register_payment' "
            "para evitar duplicado en el menú Acción del tree de facturas."
        )


def _hide_native_register_payment_action(env):
    """
    Quita el binding de la server action nativa de Odoo
    ``account.action_account_invoice_from_list`` que aparece en el menú
    Acciones del tree de facturas abriendo el wizard estándar. Nuestro
    flujo custom la reemplaza con un botón que abre el form de pago
    directamente.
    """
    action = env.ref(
        'account.action_account_invoice_from_list',
        raise_if_not_found=False,
    )
    if action and action.binding_model_id:
        action.binding_model_id = False
        _logger.info(
            "OCA backend: quitado binding de 'account.action_account_invoice_from_list' "
            "(Registrar pago nativo) del tree de facturas."
        )


def post_init_hook(env):
    """Desactiva server actions duplicadas/nativas en el tree de facturas."""
    try:
        _hide_fiserv_register_server_action(env)
    except Exception as exc:
        _logger.warning(
            "OCA backend post_init: no se pudo ajustar server action Fiserv: %s",
            exc,
        )
    try:
        _hide_native_register_payment_action(env)
    except Exception as exc:
        _logger.warning(
            "OCA backend post_init: no se pudo ajustar server action nativa: %s",
            exc,
        )
