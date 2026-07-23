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
        'issuer_code',
    )
    def _compute_shopping_payment_code(self):
        PaymentMethod = self.env['payment.method']
        PosPayment = self.env['pos.payment']
        for record in self:
            code = None


            if record.issuer_code and record.payment_method_id:
                brand = PaymentMethod.with_context(active_test=False).search([
                    ('primary_payment_method_id', '=', record.payment_method_id.id),
                    '|',
                    ('name', '=', record.issuer_name),
                    ('name', '=', record.manual_stamp),
                ], limit=1)

                if brand:
                    code = brand.shopping_payment_code

            if not code:
                code = record.payment_method_id.shopping_payment_code

            if not code:
                pos_payment = PosPayment.search(
                    [('payment_transaction_id', '=', record.id)], limit=1
                )
                if pos_payment and pos_payment.payment_method_id.shopping_payment_method_id:
                    code = pos_payment.payment_method_id.shopping_payment_method_id.payment_code

            record.shopping_payment_code = code or False
