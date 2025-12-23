# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo import api, fields, models, tools, _


class Product_pricelist_items(models.Model):
    _inherit = "product.pricelist.item"

    uom_id = fields.Many2one('uom.uom', 'Pricelist UOM')

    @api.constrains('uom_id')
    def _check_uom_id(self):
        if not self.uom_id:
            raise ValidationError(_('Sorry Please Add Price list UOM'))

    def check_get_price(self, uom=False, product=False):
        if product:
            price = product.list_price
        else:
            price = False

        if self.pricelist_id:
            if uom:
                if product:
                    for item in self.pricelist_id.item_ids:
                        if uom.id == item.uom_id.id:
                            if item.applied_on == '2_product_category' \
                                    and product.product_tmpl_id.categ_id.id == item.categ_id.id:
                                price = item.fixed_price
                            elif item.applied_on == '1_product' and (
                                    product.product_tmpl_id.id == item.product_tmpl_id.id):
                                price = item.fixed_price
                            elif item.applied_on == '0_product_variant' and (
                                    product.product_tmpl_id.id == item.product_tmpl_id.id):
                                price = item.fixed_price
                            elif item.applied_on == '3_global':
                                price = item.fixed_price
        return price

    def _compute_price(self, product, quantity, uom, date, currency=None):

        product.ensure_one()
        uom.ensure_one()

        currency = currency or self.currency_id
        currency.ensure_one()

        product_uom = product.uom_id
        if product_uom != uom:
            convert = lambda p: product_uom._compute_price(p, uom)
        else:
            convert = lambda p: p
        if self.compute_price == 'fixed':
            price = self.check_get_price(uom, product)
        elif self.compute_price == 'percentage':
            if uom.id == self.uom_id.id:
                base_price = self._compute_base_price(product, quantity, uom, date, currency)
                price = (base_price - (base_price * (self.percent_price / 100))) or 0.0
            else:
                price = float(product.list_price)
        elif self.compute_price == 'formula':
            if uom.id == self.uom_id.id:
                base_price = self._compute_base_price(product, quantity, uom, date, currency)
                # complete formula
                price_limit = base_price
                price = (base_price - (base_price * (self.price_discount / 100))) or 0.0
                if self.price_round:
                    price = tools.float_round(price, precision_rounding=self.price_round)
            else:
                price = float(product.list_price)
            if self.price_surcharge:
                price += convert(self.price_surcharge)
            if self.price_min_margin:
                price = max(price, price_limit + convert(self.price_min_margin))

            if self.price_max_margin:
                price = min(price, price_limit + convert(self.price_max_margin))
        else:  # empty self, or extended pricelist price computation logic
            price = self._compute_base_price(product, quantity, uom, date, currency)
        return price
