from odoo import models, fields, api, _


class AccountMoveInherit(models.Model):
    _inherit = "account.move"

    pricelist_id = fields.Many2one('product.pricelist', string="Pricelist")

    def product_price_update(self):
        for lines in self.invoice_line_ids.filtered(lambda l: l.product_id and l.price_unit > 0.00):
            pricelist_item = self.pricelist_id.item_ids.filtered(
                lambda l: l.compute_price == 'fixed' and l.applied_on == '1_product' and l.uom_id.id == lines.uom_id.id)
            if pricelist_item:
                each_price = self.pricelist_id.item_ids.search(
                    [('product_tmpl_id', '=', lines.product_id.product_tmpl_id.id),
                     ('compute_price', '=', 'fixed'),
                     ('applied_on', '=', '1_product'),
                     ('pricelist_id', '=', self.pricelist_id.id),
                     ('uom_id', '=', lines.uom_id.id)])
                if not each_price:
                    self.pricelist_id.write({'item_ids': [(0, 0, {'applied_on': '1_product',
                                                                  'product_id': lines.product_id.product_tmpl_id.id,
                                                                  'uom_id': lines.uom_id.id,
                                                                  'fixed_price': lines.price_unit})]})
                else:
                    each_price.fixed_price = lines.price_unit

            else:
                self.pricelist_id.write({'item_ids': [(0, 0, {'applied_on': '1_product',
                                                              'product_id': lines.product_id.product_tmpl_id.id,
                                                              'uom_id': lines.uom_id.id,
                                                              'fixed_price': lines.price_unit
                                                              })]})

    @api.onchange('invoice_line_ids')
    def onchange_product(self):
        for line in self.invoice_line_ids:
            if self.pricelist_id and self.partner_id:
                each_price = self.pricelist_id.item_ids.search(
                    [('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                     ('pricelist_id', '=', self.pricelist_id.id), ('uom_id', '=', line.product_id.uom_id.id)])
                if each_price:
                    line.price_unit = each_price[0].fixed_price

    @api.model
    def create(self, val):
        res = super(AccountMoveInherit, self).create(val)
        if self._context.get('active_model') == 'sale.order':
            sale_obj = self.env['sale.order'].browse(self._context.get('active_id'))
            res.pricelist_id = sale_obj.pricelist_id
        return res
