from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fenicio_website_id = fields.Many2one(
        'website',
        string='Sitio Web Fenicio',
        stored=True,
        config_parameter='odoo_fenicio.website_id',
        help='Sitio web donde se registrarán las ventas de Fenicio'
    )
    
    fenicio_pricelist_venta = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios de Venta Fenicio',
        stored=True,
        config_parameter='odoo_fenicio.pricelist_venta',
        help='Lista de precios de venta predeterminada para todos los productos Fenicio'
    )
    
    fenicio_pricelist_lista = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios Lista Fenicio',
        stored=True,
        config_parameter='odoo_fenicio.pricelist_lista',
        help='Lista de precios lista predeterminada para todos los productos Fenicio'
    )
    
    fenicio_pricelist_alternativo = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios Alternativo Fenicio',
        stored=True,
        config_parameter='odoo_fenicio.pricelist_alternativo',
        help='Lista de precios alternativa predeterminada para todos los productos Fenicio'
    )