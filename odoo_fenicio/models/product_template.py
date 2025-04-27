# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger('FENICIO_PRODUCT_TEMPLATE')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    product_e_fenicio = fields.Boolean('Producto e-Fenicio', default=False)
    code_e_fenicio = fields.Char('Código e-Fenicio')
    default_currency_id = fields.Many2one('res.currency', 'Moneda Fenicio', default=lambda self: self.env.company.currency_id)
    fenicio_check = fields.Boolean('Descuentos e-Fenicio', default=False)
    product_settings_ids = fields.One2many('product.setting', 'product_template_id', 'Atributos del producto')
    brand = fields.Char('Marca')
    priority_fenicio = fields.Integer('Prioridad')
    guia_talles = fields.Char('Guia Talles')

    @api.onchange('type')
    def change_type_check_fenicio(self):
        for rec in self:
            rec.fenicio_check = False

    @api.onchange('product_e_fenicio')
    def change_product_e_fenicio(self):
        for rec in self:
            rec.product_settings_ids = [(5, 0, 0)]
            rec.product_settings_ids = False
            if rec.product_e_fenicio:
                default_settings = []
                required_attributes_ids = self.env['product.attribute'].search([
                    ('base_product_attribute', '=', True),
                    ('base_product_attribute_required', '=', True),
                ])
                for attribute_id in required_attributes_ids:
                    vals = {
                        'attribute_id': attribute_id.id,
                    }
                    default_settings.append((0, 0, vals))
                rec.product_settings_ids = default_settings

    @api.constrains('product_settings_ids')
    def check_product_settings_ids(self):
        for rec in self:
            if len(rec.product_settings_ids.filtered(lambda l: not l.value_id)) > 0:
                raise ValidationError('Hay valores vacíos en las características del producto.')

    @api.model_create_multi
    def create(self, vals_list):
        new_ids = super(ProductTemplate, self).create(vals_list)
        for new_id in new_ids:
            if new_id.product_e_fenicio and not new_id.fenicio_check:
                required_attributes_ids = self.env['product.attribute'].search([
                    ('base_product_attribute', '=', True),
                    ('base_product_attribute_required', '=', True),
                ])

                set_atributos_obligatorios = set(required_attributes_ids.ids)
                set_atributos_obligatorios_producto = set(new_id.product_settings_ids.filtered(lambda l: l.base_product_attribute_required).mapped('attribute_id').ids)

                set_resultante = set_atributos_obligatorios & set_atributos_obligatorios_producto

                if len(set_resultante) != len(set_atributos_obligatorios):
                    raise UserError('Todos los atributos obligatorios deben estar en las características del producto.')

        return new_ids
