
from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fenicio_website_id = fields.Many2one(
        'website',
        string='Sitio Web Fenicio',
        config_parameter='odoo_fenicio.website_id',
        help='Sitio web donde se registrarán las ventas de Fenicio'
    )