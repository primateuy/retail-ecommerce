# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger('FENICIO_PRODUCT_PRODUCT')


class ProductProductPricelistRelation(models.Model):
    _name = 'product.product.pricelist.relation'
    _description = 'Relación entre Producto y Lista de Precios'


    product_product_id = fields.Many2one(
        'product.product',
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
    listaPrecios = fields.Many2one('product.pricelist', string='Lista de Precios')
    precios_fenicio_ids = fields.One2many('fenicio.presentacion.price', 'product_id', 'Precios Fenicio')
    indentificadores_ids = fields.One2many('product.identificadores', 'product_id', 'Identificadores')
    precios_alternativos_fenicio_ids = fields.One2many('precios.alternativos', 'product_id', 'Precios Alternativos')
    

    pricelist_relation_ids = fields.One2many(
        'product.product.pricelist.relation',
        'product_product_id',
        string='Relación de Precios'
    )

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
                

    def _get_primer_impuesto_iva(self):
        """Obtener el primer impuesto IVA de venta del producto"""
        self.ensure_one()
        for tax in self.taxes_id:
            if 'IVA' in tax.name.upper() or tax.type_tax_use == 'sale':
                return tax.amount
        return False
