# -*- coding: utf-8 -*-
"""Enlace payment.transaction -> account.payment para el flujo contable."""

from odoo import fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    getnet_account_payment_id = fields.Many2one(
        comodel_name='account.payment',
        string='Pago contable (Getnet)',
        copy=False,
        index=True,
    )
