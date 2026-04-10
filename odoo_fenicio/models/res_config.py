from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fenicio_token = fields.Char(
        string='Token de Autenticación Fenicio',
        related='company_id.fenicio_token',
        readonly=False,
    )

    fenicio_website_id = fields.Many2one(
        'website',
        string='Sitio Web Fenicio',
        related='company_id.fenicio_website_id',
        readonly=False,
        help='Sitio web donde se registrarán las ventas de Fenicio'
    )

    fenicio_compania_id = fields.Many2one(
        'res.company',
        string='Compañía Fenicio',
        related='company_id',
        readonly=True,
        help='Compañía donde se registrarán las ventas de Fenicio'
    )
    
    fenicio_pricelist_venta_id = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios de Venta Fenicio',
        related='company_id.fenicio_pricelist_venta_id',
        readonly=False,
        help='Lista de precios de venta predeterminada para todos los productos Fenicio'
    )
    
    fenicio_pricelist_lista_id = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios Lista Fenicio',
        related='company_id.fenicio_pricelist_lista_id',
        readonly=False,
        help='Lista de precios lista predeterminada para todos los productos Fenicio'
    )
    
    fenicio_pricelist_alternativo_id = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios Alternativo Fenicio',
        related='company_id.fenicio_pricelist_alternativo_id',
        readonly=False,
        help='Lista de precios alternativa predeterminada para todos los productos Fenicio'
    )

    cantidad_stock_bydefault = fields.Integer(
        string='Cantidad de Stock a mostrar por defecto',
        related='company_id.cantidad_stock_bydefault',
        readonly=False,
    )

    fenicio_sale_order_type_id = fields.Many2one(
        'sale.order.type',
        string='Tipo de Orden de Venta Fenicio',
        related='company_id.fenicio_sale_order_type_id',
        readonly=False,
        help='Tipo de orden de venta predeterminado para las ventas procesadas por Fenicio'
    )

    fenicio_stock_location_ids = fields.Many2many(
        'stock.location',
        string='Ubicaciones de Stock Fenicio',
        related='company_id.fenicio_stock_location_ids',
        readonly=False,
        help='Ubicaciones de donde se consultará el stock para Fenicio'
    )