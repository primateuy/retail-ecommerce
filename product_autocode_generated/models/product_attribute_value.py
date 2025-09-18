import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    code = fields.Char(
        string='Código del valor',
        size=10,
        help='Código corto del valor para usar en códigos automáticos. '
             'Máximo 10 caracteres. Ejemplo: L, XL, AZU, VER',
        index=True,
        copy=False,
    )
