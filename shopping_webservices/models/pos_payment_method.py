from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_pos_shopping = fields.Boolean(
        string='PDV Shopping',
        default=False,
        help='Indica que este método de pago corresponde a una integración con Shopping.'
    )

    shopping_payment_method_id = fields.Many2one(
        'shopping.payment.method',
        string='Método de Pago Shopping',
        help='Método de pago del Shopping asociado a este método de pago PDV.'
    )

    @api.constrains('is_pos_shopping', 'shopping_payment_method_id')
    def _check_shopping_payment_method(self):
        for record in self:
            if record.is_pos_shopping and not record.shopping_payment_method_id:
                raise ValidationError(
                    'Debe seleccionar un Método de Pago Shopping cuando POS Shopping está activo.'
                )
