from odoo import fields, api, models;

class StockLocation(models.Model):
    _inherit = 'stock.location'
    
    fenicio_visible = fields.Boolean(
        string='Ubicación Visible para FENICIO',
        default=False,
        help='Si está marcado, el stock de esta ubicación se enviará a Fenicio'
    )


    def write(self, vals):
        res = super(StockLocation, self).write(vals)
        
        if 'fenicio_visible' in vals and not vals['fenicio_visible']:
            companies = self.env['res.company'].search([
                ('fenicio_stock_location_ids', 'in', self.ids)
            ])
            if companies:
                for location in self:
                    companies.write({
                        'fenicio_stock_location_ids': [(3, location.id)]
                    })
        
        return res

