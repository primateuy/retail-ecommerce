from odoo import fields, models


class MercadoPagoApplications(models.Model):

    _name = 'mercado_pago.applications'
    _description = 'Mercado Pago Applications'

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    mp_user_id = fields.Many2one(
        'mercado_pago.user',
        string='Usuario MP',
        required=True,
        ondelete='cascade',
    )
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)
