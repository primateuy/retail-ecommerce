# -*- coding: utf-8 -*-
"""
Campos en pos.payment para integraciones ITD (Fiserv) cuando no existe odoo_pos_oca.

Misma semántica de columnas que odoo_pos_oca en pos.payment para Fiserv sin OCA.
"""

from odoo import api, fields, models


class PosPayment(models.Model):
    """
    Extiende cobros POS con datos que el terminal ITD y los informes esperan.
    """

    _inherit = "pos.payment"

    invoice_number = fields.Char(
        string="Número de factura",
        help="Valor enviado al servicio ITD como InvoiceNumber cuando aplica.",
    )
    is_promotion = fields.Boolean(
        string="Es promoción",
        help="Indica si el pago corresponde a una promoción.",
    )
    installments = fields.Integer(
        string="Número de cuotas",
        default=1,
        help="Cuotas enviadas al terminal ITD.",
    )
    payment_transaction_id = fields.Many2one(
        comodel_name="payment.transaction",
        string="Transacción de pago",
        help="Transacción payment.transaction asociada a este cobro POS.",
        readonly=True,
        copy=False,
    )
    pos_session_id = fields.Many2one(
        comodel_name="pos.session",
        string="Sesión POS",
        compute="_compute_pos_session_id",
        readonly=True,
        copy=False,
        store=False,
        help="Sesión del TPV derivada del pedido asociado.",
    )

    @api.depends("pos_order_id", "pos_order_id.session_id")
    def _compute_pos_session_id(self):
        """Propaga la sesión desde el pedido POS vinculado."""
        for payment in self:
            order = payment.pos_order_id
            payment.pos_session_id = order.session_id if order else False

    @api.model
    def create(self, vals):
        """
        Completa invoice_number desde el pedido si viene vacío; el resto de la
        cadena (p. ej. odoo_pos_fiserv) sigue en super().
        """
        if not vals.get("invoice_number") and vals.get("pos_order_id"):
            pos_order = self.env["pos.order"].browse(vals["pos_order_id"])
            if pos_order.exists():
                vals["invoice_number"] = pos_order.name
        return super().create(vals)
