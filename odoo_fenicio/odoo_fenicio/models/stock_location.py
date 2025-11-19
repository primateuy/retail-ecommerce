from odoo import fields, api, models;

class StockLocation(models.Model):
    _inherit = 'stock.location'
    
    fenicio_visible = fields.Boolean(
        string='Ubicación Visible para FENICIO',
        default=False,
        help='Si está marcado, el stock de esta ubicación se enviará a Fenicio'
    )