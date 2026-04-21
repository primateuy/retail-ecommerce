# -*- coding: utf-8 -*-
"""
Hooks del módulo odoo_pos_oca (integración TPV).

- pre_init_hook: migra los ir.model.data que antes declaraba este módulo y que
  ahora quedan aquí (solo pos.payment.method y el reporte de ticket de cambio)
  o al core (provider, journal, terminal, transacción). El core ya reasigna
  los suyos; aquí se aseguran los específicos del POS.
- post_init_hook: garantiza la existencia del pos.payment.method OCA y su
  enlace al payment.provider creado por el core.
"""

import logging

_logger = logging.getLogger(__name__)

# xml_ids que se quedan en odoo_pos_oca y deben permanecer reasignados aquí
# cuando la BD venía del monolito anterior. Son registros específicos del POS.
_IRMD_NAMES_MIGRATED_TO_POS = (
    'pos_payment_method_oca',
    'change_ticket_report',
    'action_report_pos_order_oca_change_ticket',
    'pos_config_view_form_inherit_oca_change_ticket',
    'pos_payment_method_form_oca',
    'pos_payment_form_oca',
)


def pre_init_hook(env):
    """Reasigna ir.model.data del POS (si venían apuntando a sí mismo)."""
    # En este caso el módulo conserva su propio nombre, así que no hay renombrado
    # real. El hook queda como extensibilidad futura. El core ya migra sus registros.
    _logger.info("odoo_pos_oca pre_init: sin renombres necesarios.")


def post_init_hook(env):
    """Garantiza pos.payment.method OCA y su enlace al provider (creado por core)."""
    try:
        _logger.info("Post-instalación odoo_pos_oca: inicio")
        _ensure_oca_pos_payment_method(env)
        _logger.info("Post-instalación odoo_pos_oca: completada")
    except Exception as exc:
        _logger.error("Post-instalación odoo_pos_oca: %s", exc, exc_info=True)


def _ensure_oca_pos_payment_method(env):
    """
    Crea pos.payment.method con use_payment_terminal=oca si no hay ninguno.
    Registra el ir.model.data ``odoo_pos_oca.pos_payment_method_oca`` para que
    otros módulos/data puedan referenciarlo por xml_id.
    """
    try:
        pos_pm = env['pos.payment.method'].search(
            [('use_payment_terminal', '=', 'oca')], limit=1,
        )
        if not pos_pm:
            receivable = env['account.account'].search(
                [
                    ('account_type', '=', 'asset_receivable'),
                    ('company_id', '=', env.company.id),
                ],
                limit=1,
            )
            if not receivable:
                _logger.error('No hay cuenta por cobrar; no se crea método POS OCA')
                return
            provider = env['payment.provider'].search([('code', '=', 'oca')], limit=1)
            vals = {
                'name': 'OCA POSLink',
                'use_payment_terminal': 'oca',
                'receivable_account_id': receivable.id,
                'is_cash_count': False,
                'active': True,
                'sequence': 10,
                'url_webservice': 'https://api.oca.com',
                'codigo_sistema': '1',
                'codigo_terminal': '001',
                'client_app_id': '1',
                'codigo_sucursal': 1,
            }
            pos_pm = env['pos.payment.method'].create(vals)
            _logger.info('Método POS OCA creado en post_init')
        env['ir.model.data']._update_xmlids([{
            'xml_id': 'odoo_pos_oca.pos_payment_method_oca',
            'record': pos_pm,
            'noupdate': True,
        }])
    except Exception as exc:
        _logger.error('_ensure_oca_pos_payment_method: %s', exc, exc_info=True)
