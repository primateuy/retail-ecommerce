# -*- coding: utf-8 -*-
"""
Extiende account.payment para mostrar la sesión POS vinculada a la transacción.

Misma intención que la vista ``account_payment_views`` de odoo_pos_oca: trazabilidad
desde el pago contable hasta la caja (sesión) cuando existe ``payment_transaction_id``
con orden POS.
"""

from odoo import api, fields, models


class AccountPayment(models.Model):
    """
    Campo calculado de solo lectura con la sesión POS de origen (si aplica).
    """

    _inherit = "account.payment"

    pos_session_id = fields.Many2one(
        comodel_name="pos.session",
        string="Sesión POS",
        compute="_compute_pos_session_id",
        readonly=True,
        help="Sesión del TPV si el pago proviene de una transacción POS enlazada.",
    )

    @api.depends("payment_transaction_id", "payment_transaction_id.pos_order_id")
    def _compute_pos_session_id(self):
        """
        Resuelve la sesión desde ``payment.transaction.pos_order_id.session_id``.
        """
        for pay in self:
            tx = pay.payment_transaction_id
            order = tx.pos_order_id if tx else False
            pay.pos_session_id = order.session_id if order else False
