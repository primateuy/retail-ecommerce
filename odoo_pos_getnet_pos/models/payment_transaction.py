# -*- coding: utf-8 -*-
"""Enlaces payment.transaction -> orden/pago POS."""

from odoo import fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    getnet_pos_order_id = fields.Many2one(
        comodel_name='pos.order', string='Orden POS (Getnet)',
        copy=False, index=True)
    getnet_pos_payment_id = fields.Many2one(
        comodel_name='pos.payment', string='Pago POS (Getnet)',
        copy=False, index=True)
