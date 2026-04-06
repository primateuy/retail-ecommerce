# -*- coding: utf-8 -*-
"""
Sesión POS visible en account.payment vía la transacción enlazada al pedido TPV.
"""

from odoo import api, fields, models


class AccountPayment(models.Model):
    """Añade sesión POS cuando el pago contable proviene de un cobro con transacción ITD."""

    _inherit = "account.payment"

    pos_session_id = fields.Many2one(
        comodel_name="pos.session",
        string="Sesión POS",
        compute="_compute_pos_session_id",
        readonly=True,
        help="Sesión del TPV si la transacción de pago está ligada a un pos.order.",
    )

    @api.depends(
        "payment_transaction_id",
        "payment_transaction_id.pos_order_id",
        "payment_transaction_id.pos_order_id.session_id",
    )
    def _compute_pos_session_id(self):
        """Resuelve la sesión a partir del pedido POS de la transacción."""
        for pay in self:
            tx = pay.payment_transaction_id
            order = tx.pos_order_id if tx else False
            pay.pos_session_id = order.session_id if order else False
