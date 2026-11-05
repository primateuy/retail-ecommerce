from odoo import api, fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    shopping_payment_code = fields.Char(
        string='Código Shopping',
        compute='_compute_shopping_payment_code',
        store=True,
    )

    # manual_stamp (pos_forum_manual_payment) no va en depends porque ese módulo no es
    # dependencia; se escribe en el create junto con el resto, así que igual se considera.
    @api.depends(
        'payment_method_id',
        'payment_method_id.shopping_payment_code',
        'issuer_code',
        'issuer_name',
        'pos_payment_id',
        'pos_payment_id.payment_method_id.shopping_payment_method_id.payment_code',
    )
    def _compute_shopping_payment_code(self):
        """Resuelve el código de forma de pago del shopping para la transacción.

        Orden de prioridad:
            1. Marca (payment.method hija del método de la transacción) cuyo nombre
               coincide con issuer_name o manual_stamp.
            2. Método de Pago Shopping configurado en el método de pago PDV.
            3. Código Shopping del método de pago de la transacción.
        """
        PaymentMethod = self.env['payment.method'].with_context(active_test=False)
        PosPayment = self.env['pos.payment']
        has_manual_stamp = 'manual_stamp' in self._fields
        for record in self:
            code = False

            brand_names = [
                name for name in (
                    record.issuer_name,
                    record.manual_stamp if has_manual_stamp else False,
                ) if name
            ]
            if record.payment_method_id and brand_names:
                brand = PaymentMethod.search([
                    ('primary_payment_method_id', '=', record.payment_method_id.id),
                    ('name', 'in', brand_names),
                    ('shopping_payment_code', '!=', False),
                ], limit=1)
                code = brand.shopping_payment_code

            if not code:
                # pos_payment_id llega en el create; payment_transaction_id del pago POS
                # se enlaza recién después, por eso la búsqueda inversa queda de respaldo.
                pos_payment = record.pos_payment_id
                if not pos_payment and record.id:
                    pos_payment = PosPayment.search(
                        [('payment_transaction_id', '=', record.id)], limit=1
                    )
                code = pos_payment.payment_method_id.shopping_payment_method_id.payment_code

            if not code:
                code = record.payment_method_id.shopping_payment_code

            record.shopping_payment_code = code or False
