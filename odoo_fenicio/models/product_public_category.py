from odoo import fields, api, models;

class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    fenicio_code = fields.Char('Código Categoría Fenicio', help='Código de la categoría para integración con fenicio');



    