# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.exceptions import ValidationError

class ResCompany(models.Model):
    _inherit = 'res.company'

    fenicio_token = fields.Char(string='Token de Autenticación Fenicio')
    fenicio_website_id = fields.Many2one('website', string='Sitio Web Fenicio')
    fenicio_pricelist_venta_id = fields.Many2one('product.pricelist', string='Lista de Precios de Venta Fenicio')
    fenicio_pricelist_lista_id = fields.Many2one('product.pricelist', string='Lista de Precios Lista Fenicio')
    fenicio_pricelist_alternativo_id = fields.Many2one('product.pricelist', string='Lista de Precios Alternativo Fenicio')
    fenicio_stock_location_ids = fields.Many2many('stock.location', string='Ubicaciones de Stock Fenicio', domain=[('usage', '=', 'internal'), ('fenicio_visible', '=', True)])

    @api.constrains('fenicio_token')
    def _check_fenicio_token_unique(self):
        for rec in self:
            if rec.fenicio_token:
                duplicate = self.search([
                    ('fenicio_token', '=', rec.fenicio_token),
                    ('id', '!=', rec.id)
                ])
                if duplicate:
                    raise ValidationError("El token de Fenicio ya está siendo utilizado por la compañía: %s. Cada compañía debe tener un token único." % duplicate[0].name)

    @api.constrains('fenicio_website_id')
    def _check_fenicio_website_unique(self):
        for rec in self:
            if rec.fenicio_website_id:
                duplicate = self.search([
                    ('fenicio_website_id', '=', rec.fenicio_website_id.id),
                    ('id', '!=', rec.id)
                ])
                if duplicate:
                    raise ValidationError("El sitio web '%s' ya está asignado a la integración de Fenicio en la compañía: %s." % (rec.fenicio_website_id.name, duplicate[0].name))
