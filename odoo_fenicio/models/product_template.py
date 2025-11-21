# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger('FENICIO_PRODUCT_TEMPLATE')

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


class WizardConfirmation(models.TransientModel):
    _name = 'wizard.confirmation'
    _description = 'Confirmar acción'

    

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    product_e_fenicio = fields.Boolean('Producto e-Fenicio', default=False)
    code_e_fenicio = fields.Char(
        'Código e-Fenicio', 
        help='Código del producto para integración con e-Fenicio',
        compute='_compute_code_e_fenicio',
        store=True,
        readonly=False
    )
    default_currency_id = fields.Many2one('res.currency', 'Moneda Fenicio', default=lambda self: self.env.company.currency_id)
    fenicio_check = fields.Boolean('Descuentos e-Fenicio', default=False)
    product_settings_ids = fields.One2many('product.setting', 'product_template_id', 'Atributos del producto')
    brand = fields.Char('Marca')
    priority_fenicio = fields.Integer(
    string='Prioridad FENICIO',
    store=True,
    readonly=False,
    compute='website_sequence_compute'
    )
    guia_talles = fields.Char('Guia Talles')

    guia_talle_id = fields.Many2one(
        'guia.talles',
        string='Guía de Talles',
        help='Seleccionar la guía de talles correspondiente a este producto'
    )
    
    guia_talle_code = fields.Char(
        string='Código Guía Talle',
        related='guia_talle_id.code',
        store=True,
        readonly=True,
        help='Código de la guía de talles para integración con e-Fenicio'
    )
    
    guia_talle_image = fields.Binary(
        string='Imagen Guía Talle',
        related='guia_talle_id.image',
        readonly=True
    )

    pricelist_relation_ids = fields.One2many(
        'product.pricelist.relation',
        'product_template_id',
        string='Relación de Precios'
    )

    descripcion_fenicio = fields.Text('Descripción e-Fenicio');




    @api.depends('website_sequence')
    def website_sequence_compute(self):
        for rec in self:
            rec.priority_fenicio = rec.website_sequence if rec.website_sequence else 0;

    def write(self, vals):
        res = super(ProductTemplate, self).write(vals)
        for rec in self:
            if rec.pricelist_relation_ids:
                for variante in rec.product_variant_ids:
                    variante.pricelist_relation_ids = [(5, 0, 0)]
                    for relation in rec.pricelist_relation_ids:
                        variante.pricelist_relation_ids = [(0, 0, {
                            'product_product_id': variante.id,
                            'precio_venta': relation.precio_venta.id,
                            'precio_lista': relation.precio_lista.id,
                            'precio_alternativo': relation.precio_alternativo.id,
                        })]

                    
        return res
    
    @api.constrains('pricelist_relation_ids')
    def _check_pricelist_relation_limit(self):
        for record in self:
            if len(record.pricelist_relation_ids) > 1:
                raise ValidationError('Solo se puede agregar una línea en la tabla de Listas de Precios.')

    @api.depends('default_code', 'product_e_fenicio')
    def _compute_code_e_fenicio(self):
        """Computa el código e-Fenicio basado en el default_code"""
        for rec in self:
            if rec.product_e_fenicio and rec.default_code:
                rec.code_e_fenicio = rec.default_code
            else:
                rec.code_e_fenicio = rec.code_e_fenicio or ''

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
