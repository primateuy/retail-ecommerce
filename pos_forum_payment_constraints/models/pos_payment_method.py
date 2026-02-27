# -*- coding: utf-8 -*-
from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    readonly_opening_cash = fields.Boolean(
        string="Opening Cash Readonly",
        help="Si está activo, el monto de apertura en caja será solo lectura para este método.",
        default=False,
    )
    readonly_closing_non_cash = fields.Boolean(
        string="Closing Non-Cash Readonly",
        help="Si está activo, el monto contado en cierre será solo lectura para este método.",
        default=False,
    )
    limit_closing_cash_to_balance = fields.Boolean(
        string="Limit Closing Cash to Balance",
        help="Si está activo, el monto contado en cierre no puede superar el saldo esperado.",
        default=False,
    )
