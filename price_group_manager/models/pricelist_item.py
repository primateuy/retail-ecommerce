from odoo import models, fields, api
from odoo.exceptions import UserError


class PricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    solo_lectura_campos = fields.Boolean(compute='compute_solo_lectura_campos')
    visible_cantidad_minima = fields.Boolean(compute='compute_solo_lectura_campos')

    @api.depends('pricelist_id')
    def compute_solo_lectura_campos(self):
        for rec in self:
            s = False
            visible_cantidad_minima = True
            if rec.pricelist_id:
                x = self.env['x_price_group'].search([('lista_precio_id', '=', rec.pricelist_id.id)], limit=1)
                if len(x) > 0:
                    s = True

                x_line = self.env['x_price_group_line'].search([('price_list_item_id', '=', rec.id)], limit=1)
                if not x_line.activo:
                    visible_cantidad_minima = False

            rec.solo_lectura_campos = s
            rec.visible_cantidad_minima = visible_cantidad_minima

    def unlink(self):
        for rec in self:
            r = self.env['x_price_group_line'].search([('price_list_item_id', '=', rec.id)], limit=1)
            if len(r) > 0:
                raise UserError('No puede eliminar una regla de precios que se creo a partir de un agrupador de precio')

        res = super(PricelistItem, self).unlink()
        return res
