from odoo import _, fields, models


class MpPaymentTransaction(models.Model):

    _name = 'mp.payment.transaction'
    _description = 'Mercado Pago Payment Transaction'
    _order = 'create_date desc'

    name = fields.Char(string='Referencia', required=True)
    payment_id = fields.Many2one(
        'account.payment',
        string='Pago',
    )
    payment_method_id = fields.Many2one(
        'account.payment.method',
        string='Metodo de pago',
        required=True,
    )
    provider_id = fields.Many2one(
        'payment.provider',
        string='Proveedor',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
    )
    amount = fields.Float(string='Importe')
    pos_order_id = fields.Many2one(
        'pos.order',
        string='Orden de PdV',
    )
