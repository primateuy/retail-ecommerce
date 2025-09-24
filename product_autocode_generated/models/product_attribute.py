from odoo import fields, models


class ProductAttribute(models.Model):
    _inherit = 'product.attribute'
    
    include_in_code = fields.Boolean(
        string='Incluir en código automático',
        default=False,
        help='Si está activo, los valores de este atributo se incluirán '
             'en la generación del código de la variante del producto',
    )
