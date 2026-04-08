from odoo import api, fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    shopping_payment_code = fields.Char(
        string='Código Shopping',
        compute='_compute_shopping_payment_code',
        store=True,
    )

    @api.depends(
        'payment_method_id',
        'payment_method_id.shopping_payment_code',
        'pos_payment_id',
        'pos_payment_id.payment_method_id',
        'pos_payment_id.payment_method_id.shopping_payment_method_id',
    )
    def _compute_shopping_payment_code(self):
        for record in self:
            code = record.payment_method_id.shopping_payment_code

            if not code:
                pos_payment = self.env['pos.payment'].search(
                    [('payment_transaction_id', '=', record.id)], limit=1
                )
                if pos_payment and pos_payment.payment_method_id.shopping_payment_method_id:
                    code = pos_payment.payment_method_id.shopping_payment_method_id.payment_code

            record.shopping_payment_code = code or False
