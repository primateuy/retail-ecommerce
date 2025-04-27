# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    fenicio_type = fields.Selection([
        ('variante', 'Variante'),
        ('presentacion', 'Presentación'),
    ], string='Tipo Fenicio', help='Comportamiento de atributos en variantes para integración con fenicio')
    base_product_attribute = fields.Boolean('Es un atributo de producto', default=False)
    base_product_attribute_required = fields.Boolean('Atributo obligatorio', default=False)


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    fenicio_attribute_value_code = fields.Char('Código Variante Fenicio')
