# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger('FENICIO_PRODUCT_PRODUCT')


class PrecioListaVentaPresentacion(models.Model):
    _name = 'fenicio.presentacion.price'
    _description = 'Precio Venta y Lista de una presentacion'

    name = fields.Char(compute='compute_name')
    product_id = fields.Many2one('product.product', 'Producto', ondelete='cascade')
    alternative_price_id = fields.Many2one('precios.alternativos', 'Precio Alternativo', ondelete='cascade')
    price_type = fields.Selection([
        ('precioLista', 'Precio Lista'),
        ('precioVenta', 'Precio Venta')
    ], string="Tipo Precio", default='precioLista')
    currency_id = fields.Many2one('res.currency', 'Moneda')
    price = fields.Float('Precio Fenicio')

    def compute_name(self):
        for rec in self:
            name = ''
            if rec.currency_id:
                name = rec.price_type + '-' + rec.currency_id.display_name + '-' + str(rec.price)
            rec.name = name


class ProductIdentifiers(models.Model):
    _name = 'product.identificadores'
    _description = 'Product Identifiers'

    product_id = fields.Many2one('product.product', string="Producto", ondelete='cascade')
    code = fields.Char("Código")
    value = fields.Char("Valor")


class ProductAlternativePrice(models.Model):
    _name = 'precios.alternativos'
    _description = 'Precios alternativos'

    product_id = fields.Many2one('product.product', string="Producto", ondelete='cascade')
    code = fields.Char("Código")
    precios_lista_venta_ids = fields.One2many('fenicio.presentacion.price', 'alternative_price_id', 'Precios Alternativos')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    fenicio_sale_price = fields.Float('Precio Venta Fenicio')
    precios_fenicio_ids = fields.One2many('fenicio.presentacion.price', 'product_id', 'Precios Fenicio')
    indentificadores_ids = fields.One2many('product.identificadores', 'product_id', 'Identificadores')
    precios_alternativos_fenicio_ids = fields.One2many('precios.alternativos', 'product_id', 'Precios Alternativos')

    @api.constrains('default_code')
    def check_unique_fencio_default_code(self):
        for rec in self:
            if rec.default_code:
                row_ids = self.env['product.product'].search([
                    ('default_code', '=', rec.default_code),
                    ('product_tmpl_id.product_e_fenicio', '=', True)
                ], limit=2)
                if len(row_ids) == 2:
                    raise ValidationError(f'Ya existe un producto con el SKU {rec.default_code}')

    # def get_codigo_variante(self):
    #     self.ensure_one()
    #     for ptav_id in self.product_template_attribute_value_ids:
    #         if ptav_id.attribute_id.tipo == 'variante':
    #             return ptav_id.product_attribute_value_id.codigo
    #     return ''

    # def get_product_name(self):
    #     self.ensure_one()
    #     product_templete_code = self.product_tmpl_id.codigo
    #     variante_code = self.get_codigo_variante() or product_templete_code
    #
    #     configuraciones_variantes_tipo_variante_ids = self.product_tmpl_id.attribute_line_ids.filtered(lambda l: l.attribute_id.tipo == 'variante' and l.attribute_id in self.product_template_attribute_value_ids.mapped('attribute_id'))
    #     for attribute_line_id in configuraciones_variantes_tipo_variante_ids:
    #         if len(attribute_line_id.value_ids) == 1:
    #             variante_code = self.product_tmpl_id.codigo or product_templete_code
    #
    #     nombre = f'{product_templete_code}_{variante_code}'
    #     return nombre
