from odoo import models, fields, api


class PricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    solo_lectura_campos = fields.Boolean(compute='compute_solo_lectura_campos')

    @api.depends('pricelist_id')
    def compute_solo_lectura_campos(self):
        for rec in self:
            s = False
            if rec.pricelist_id:
                x = self.env['x_price_group'].search([('lista_precio_id', '=', rec.pricelist_id.id)], limit=1)
                if len(x) > 0:
                    s = True
            rec.solo_lectura_campos = s

    # aplicar_agrupador = fields.Boolean('Aplicar agrupador', default=False)
    # price_group_id = fields.Many2one('x_price_group', 'Agrupador de Precio', help='Agrupador de precio específico para aplicar esta regla')

    # @api.onchange('aplicar_agrupador')
    # def change_aplicar_agrupador(self):
    #     for rec in self:
    #         if rec.aplicar_agrupador:
    #             rec.applied_on = '3_global'
    #
    # def _is_applicable_for(self, product, qty_in_product_uom):
    #     """Check whether the current rule is valid for the given product & qty.
    #
    #     Note: self.ensure_one()
    #
    #     :param product: product record (product.product/product.template)
    #     :param float qty_in_product_uom: quantity, expressed in product UoM
    #     :returns: Whether rules is valid or not
    #     :rtype: bool
    #     """
    #     self.ensure_one()
    #     product.ensure_one()
    #     res = True
    #
    #     is_product_template = product._name == 'product.template'
    #     if self.min_quantity and qty_in_product_uom < self.min_quantity:
    #         res = False
    #
    #     elif self.applied_on == "2_product_category":
    #         if (
    #             product.categ_id != self.categ_id
    #             and not product.categ_id.parent_path.startswith(self.categ_id.parent_path)
    #         ):
    #             res = False
    #     else:
    #         # Applied on a specific product template/variant
    #         if is_product_template:
    #             if self.applied_on == "1_product" and product.id != self.product_tmpl_id.id:
    #                 res = False
    #             elif self.applied_on == "0_product_variant" and not (
    #                 product.product_variant_count == 1
    #                 and product.product_variant_id.id == self.product_id.id
    #             ):
    #                 # product self acceptable on template if has only one variant
    #                 res = False
    #         else:
    #             if self.applied_on == "1_product" and product.product_tmpl_id.id != self.product_tmpl_id.id:
    #                 res = False
    #             elif self.applied_on == "0_product_variant" and product.id != self.product_id.id:
    #                 res = False
    #
    #     if self.aplicar_agrupador and self.price_group_id:
    #         product._compute_current_price_group()
    #         if product.x_current_price_group_id != self.price_group_id:
    #             res = False
    #
    #     return res
