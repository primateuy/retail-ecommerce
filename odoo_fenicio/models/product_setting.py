# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductSetting(models.Model):
    _name = 'product.setting'
    _description = 'Característica de Producto'

    product_template_id = fields.Many2one('product.template', 'Producto')
    attribute_id = fields.Many2one('product.attribute', 'Atributo')
    value_id = fields.Many2one('product.attribute.value', 'Valor')
    base_product_attribute_required = fields.Boolean(related='attribute_id.base_product_attribute_required')
