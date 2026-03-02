# -*- coding: utf-8 -*-
"""
Migración: Promociones por proveedor y incompatibilidades con loyalty.program

- Asigna proveedor OCA a promociones que no tengan payment_provider_id
  (antes se podía configurar solo por método de pago).
- El campo incompatible_promotion_ids pasa a apuntar a loyalty.program;
  los datos antiguos (relación con payment.method.promotion) no se migran.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo.api import Environment
    env = Environment(cr, 1, {})
    Promotion = env['payment.method.promotion']
    try:
        without_provider = Promotion.search([('payment_provider_id', '=', False)])
        if not without_provider:
            return
        provider = env['payment.provider'].search([('code', '=', 'oca')], limit=1)
        if not provider:
            _logger.warning(
                'Migración promociones: no se encontró proveedor OCA; '
                'asigne manualmente el proveedor a las promociones existentes.'
            )
            return
        without_provider.write({'payment_provider_id': provider.id})
        _logger.info(
            'Migración promociones: asignado proveedor OCA a %s promoción(es).',
            len(without_provider),
        )
    except Exception as e:
        _logger.exception('Error en migración promociones: %s', e)
