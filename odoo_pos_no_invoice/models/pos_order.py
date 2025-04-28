from odoo import models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _generate_pos_order_invoice(self):
        ctx = dict(self.env.context)
        ctx['generate_pdf'] = False
        self = self.with_context(ctx)
        res = super(PosOrder, self)._generate_pos_order_invoice()
        return res
