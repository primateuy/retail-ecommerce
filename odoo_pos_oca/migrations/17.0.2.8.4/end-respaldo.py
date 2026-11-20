# -*- coding: utf-8 -*-
"""Marca los cobros OCA que ya se registraron por el POS de respaldo (Forum, 2026-11-20).

Es un script `end-`: corre con todos los módulos cargados, porque los proveedores manuales
(`forum_manual`) los define `pos_forum_manual_payment`, que depende de este módulo.

Hasta esta versión el cobro del pinpad que la cajera pasaba por un método manual con la
misma autorización quedaba como cobro sin venta. Se recorren las transacciones de pagos
del PDV con autorización de los últimos 60 días y se marca el cobro OCA que registraron.
"""
import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    manuales = env['payment.transaction'].search([
        ('provider_id.code', '!=', 'oca'),
        ('pos_payment_id', '!=', False),
        ('authorization_code', '!=', False),
        ('create_date', '>=', fields.Datetime.now() - timedelta(days=60)),
    ], order='id')
    marcados = manuales._oca_marcar_cobro_registrado_por_respaldo()
    _logger.info(
        'OCA: %s cobros marcados como registrados por respaldo (de %s pagos con autorización).',
        len(marcados), len(manuales),
    )
