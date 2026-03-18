from odoo import fields, models


class MpPendingOrder(models.Model):
    _name = 'mp.pending.order'
    _description = 'MercadoPago Pending Order'

    name = fields.Char(string='External Reference', required=True, index=True)
    session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        required=True,
        ondelete='cascade',
    )
    order_data = fields.Text(string='Order Data', required=True)
