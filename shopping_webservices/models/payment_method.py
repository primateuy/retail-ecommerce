from odoo import models, fields


class PaymentMethod(models.Model):
    _inherit = 'payment.method'

    shopping_payment_code = fields.Char(string='Código Shopping')
