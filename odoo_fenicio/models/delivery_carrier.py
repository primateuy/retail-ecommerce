# -*- coding: utf-8 -*-

from odoo import fields, models


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    sale_order_type_id = fields.Many2one(
        'sale.order.type',
        string='Tipo de Orden de Venta',
        help='Tipo de orden de venta que se asignará a los pedidos creados con este método de envío',
    )