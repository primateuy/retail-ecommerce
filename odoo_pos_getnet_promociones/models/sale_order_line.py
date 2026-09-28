# -*- coding: utf-8 -*-
"""La línea de descuento de la promoción, trazable hasta la factura.

Del pedido del POS pasa al sale.order y de ahí a la factura con la promoción y
el ticket del cobro Getnet. La cuenta de la línea de factura es la de la
promoción: descuentos concedidos si financia la empresa, reintegro a reclamar
si financia el banco.
"""

from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    getnet_promocion_id = fields.Many2one(
        'getnet.promocion', string='Promoción Getnet', readonly=True,
        copy=False, ondelete='restrict', index='btree_not_null')
    getnet_ticket = fields.Char(string='Ticket Getnet', readonly=True, copy=False)

    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)
        if self.getnet_promocion_id:
            vals['getnet_promocion_id'] = self.getnet_promocion_id.id
            vals['getnet_ticket'] = self.getnet_ticket
            vals['account_id'] = self.getnet_promocion_id.cuenta_id.id
        return vals


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    getnet_promocion_id = fields.Many2one(
        'getnet.promocion', string='Promoción Getnet', readonly=True,
        copy=False, ondelete='restrict', index='btree_not_null')
    getnet_ticket = fields.Char(string='Ticket Getnet', readonly=True, copy=False)


class PosBackendApp(models.AbstractModel):
    _inherit = 'pos_backend.app'

    def _get_order_line_data(self, line):
        """En el ticket, la línea de la promoción se lee con su nombre."""
        datos = super()._get_order_line_data(line)
        if line.getnet_promocion_id:
            datos['product_name'] = line.description or datos['product_name']
        return datos

    def _get_return_line_data(self, line):
        """Lo que se devuelve por unidad ya descuenta la promoción."""
        datos = super()._get_return_line_data(line)
        if line.getnet_promocion_id:
            return datos
        promocion = line.order_id.line_ids.getnet_promocion_id[:1]
        if promocion and not line.is_reward_line:
            datos['unit_refund'] = datos['unit_refund'] * (1 - promocion.porcentaje / 100)
        return datos
