from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    code = fields.Char(
        string='Código de categoría',
        size=10,
        help='Código corto de la categoría para usar en códigos automáticos. '
             'Máximo 10 caracteres. Ejemplo: ROPA, CALZ, ACC',
        index=True,
        copy=False,
    )
