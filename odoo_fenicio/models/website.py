# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.exceptions import ValidationError


class Website(models.Model):
    _inherit = 'website'

    fenicio_token = fields.Char(string='Token de Autenticación Fenicio')
    fenicio_pricelist_venta_id = fields.Many2one('product.pricelist', string='Lista de Precios de Venta Fenicio')
    fenicio_pricelist_lista_id = fields.Many2one('product.pricelist', string='Lista de Precios Lista Fenicio')
    fenicio_pricelist_alternativo_id = fields.Many2one('product.pricelist', string='Lista de Precios Alternativo Fenicio')
    fenicio_cantidad_stock_bydefault = fields.Integer(string='Cantidad de Stock a mostrar por defecto')
    fenicio_sale_order_type_id = fields.Many2one('sale.order.type', string='Tipo de Orden de Venta Fenicio')

    fenicio_loyalty_program_id = fields.Many2one(
        'loyalty.program',
        string='Programa de Lealtad Fenicio',
        domain=[('program_type', '=', 'loyalty'), ('active', '=', True)],
    )

    fenicio_stock_location_ids = fields.Many2many(
        'stock.location',
        relation='fenicio_website_stock_location_rel',
        column1='website_id',
        column2='location_id',
        string='Ubicaciones de Stock Fenicio',
        domain=[('usage', '=', 'internal'), ('fenicio_visible', '=', True)]
    )

    @api.constrains('fenicio_token')
    def _check_fenicio_token_unique(self):
        for rec in self:
            if rec.fenicio_token:
                duplicate = self.search([
                    ('fenicio_token', '=', rec.fenicio_token),
                    ('id', '!=', rec.id)
                ])
                if duplicate:
                    raise ValidationError(
                        "El token de Fenicio ya está siendo utilizado por el sitio web: %s." % duplicate[0].name
                    )