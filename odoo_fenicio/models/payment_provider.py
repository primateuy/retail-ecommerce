
from odoo import fields, models

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('fenicio', 'Fenicio')],
        ondelete={'fenicio': 'set default'}
    )