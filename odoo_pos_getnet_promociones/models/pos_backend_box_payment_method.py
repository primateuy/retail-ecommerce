# -*- coding: utf-8 -*-
"""El modo de promociones se elige por medio de pago (o sea, por caja)."""

from odoo import fields, models


class PosBackendBoxPaymentMethod(models.Model):
    _inherit = 'pos_backend.box.payment.method'

    getnet_modo_promociones = fields.Selection(
        [('auto', 'Automático (lee la tarjeta)'),
         ('manual', 'Manual (elige el cajero)'),
         ('off', 'Sin promociones')],
        string='Modo de promociones Getnet', default='auto', required=True,
        help='Automático: antes de cobrar se lee la tarjeta en el pinpad y se '
             'aplica sola la promoción que corresponda; si la lectura falla, '
             'esa venta pasa a manual con un aviso. Manual: el cajero elige '
             '«Getnet · <promo>». El cambio rige desde el próximo cobro.',
    )
