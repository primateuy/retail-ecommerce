# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    codigo = fields.Char('Código Atributo Fenicio', help='Código del atributo para integración con fenicio');
    fenicio_type = fields.Selection([
        ('variante', 'Variante'),
        ('presentacion', 'Presentación'),
    ], string='Tipo Fenicio', help='Comportamiento de atributos en variantes para integración con fenicio')
    base_product_attribute = fields.Boolean('Es una Característica FENICIO del producto', default=False)
    base_product_attribute_required = fields.Boolean('Atributo obligatorio', default=False)


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    fenicio_attribute_value_code = fields.Char('Código Variante Fenicio')
    excluir_valor_fenicio = fields.Boolean(
        string='Excluir Valor Fenicio',
        default=False,
        help='Si está activo, este valor no se incluye en el nombre de la variante enviada a Fenicio.'
    )
