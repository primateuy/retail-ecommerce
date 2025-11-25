from odoo import models, fields

class ProductPricelistRelation(models.Model):
    _name = 'product.pricelist.relation'
    _description = 'Relación entre Producto y Lista de Precios'


    product_template_id = fields.Many2one(
        'product.template',
        string='Producto',
        required=True,
        ondelete='cascade'
    )
    
    precio_venta = fields.Many2one(
        'product.pricelist',
        string='Precio Venta',
        required=True
    )

    precio_lista = fields.Many2one(
        'product.pricelist',
        string='Precio Lista',
        required=True
    )

    precio_alternativo = fields.Many2one(
        'product.pricelist',
        string='Precio Alternativo',
        required=False
    )
