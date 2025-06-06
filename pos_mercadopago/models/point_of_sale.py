from odoo import models, fields

class posConfigInherit(models.Model):
    _inherit = 'pos.config'

    mp_tills = fields.Many2one(
        'store.tills',
        string="MercadoPago Tills",
        default=False
    )