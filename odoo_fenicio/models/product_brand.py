from odoo import models, api, fields;


class ProductBrand(models.Model):
    _inherit = 'product.brand'

    fenicio_brand_id = fields.Char(
        string='ID de Marca en FENICIO',
        help='Identificador único de la marca en el sistema FENICIO'
    )