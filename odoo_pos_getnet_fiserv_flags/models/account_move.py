# -*- coding: utf-8 -*-
"""«Pagar» de la factura (Fiserv) también carga las facturas origen de Getnet."""

from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _fiserv_register_payment_context(self, invoices):
        """
        Con Fiserv habilitado, «Pagar» abre el form del pago con las facturas
        en ``fiserv_source_invoice_ids``. Si el contador elige ahí un método
        Getnet, sin esto el cobro Getnet saldría con FacturaNro=0 y sin los
        montos de la ley 19210 aunque la factura estuviera a la vista.
        """
        ctx = super()._fiserv_register_payment_context(invoices)
        cobros = invoices.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))
        if cobros:
            ctx['default_getnet_source_invoice_ids'] = [(6, 0, cobros.ids)]
        return ctx
