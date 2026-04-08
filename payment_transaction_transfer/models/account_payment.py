# -*- coding: utf-8 -*-
"""
Extensión de account.payment para listar las transacciones de pago que originaron
una transferencia interna creada desde el asistente (`payment.transaction`).
"""

from odoo import fields, models


class AccountPayment(models.Model):
    """
    Relaciona pagos contables con `payment.transaction` cuando el pago es la
    transferencia interna generada por el asistente del módulo.

    El enlace directo Many2one está en `payment.transaction.transfer_payment_id`;
    aquí se declara el One2many inverso y un One2many relacionado para ver las
    mismas líneas desde el pago emparejado (el otro extremo de la transferencia).
    """

    _inherit = "account.payment"

    payment_transaction_ids = fields.One2many(
        comodel_name="payment.transaction",
        inverse_name="transfer_payment_id",
        string="Transacciones de pago (asistente)",
        help=(
            "Transacciones de pago incluidas en el lote que generó esta "
            "transferencia interna desde el asistente."
        ),
    )
    # Bloque: mismo conjunto que `payment_transaction_ids` del otro extremo (pago emparejado de la transferencia interna).
    transfer_paired_transaction_ids = fields.One2many(
        related="paired_internal_transfer_payment_id.payment_transaction_ids",
        string="Transacciones de pago (extremo emparejado)",
        readonly=True,
    )

    def _pt_transfer_get_linked_transactions(self):
        """
        Obtiene las `payment.transaction` vinculadas a esta transferencia interna,
        sea el pago donde el asistente escribió el enlace o su par.

        Se usa al revertir el estado funcional cuando el asiento deja de estar
        publicado o se cancela.

        :return: recordset de `payment.transaction`.
        """
        self.ensure_one()
        txs = self.payment_transaction_ids
        if not txs and self.paired_internal_transfer_payment_id:
            txs = self.paired_internal_transfer_payment_id.payment_transaction_ids
        return txs

    def _pt_transfer_revert_linked_transactions_state(self):
        """
        Pone en «Pendiente» el estado de transferencia en todas las transacciones
        asociadas a estos pagos (sin borrar el vínculo histórico con el pago).

        :return: None
        """
        Transaction = self.env["payment.transaction"]
        all_txs = Transaction.browse()
        for pay in self:
            all_txs |= pay._pt_transfer_get_linked_transactions()
        if all_txs:
            all_txs.write({"transfer_state": "pending"})

    def unlink(self):
        """
        Antes de eliminar el pago, libera las transacciones de pago vinculadas
        para que vuelvan a «Pendiente» y no bloqueen el borrado por integridad.

        :return: resultado del `unlink` estándar.
        """
        # Bloque: revertir estado y quitar el enlace para evitar `restrict` en el Many2one.
        Transaction = self.env["payment.transaction"]
        all_txs = Transaction.browse()
        for pay in self:
            all_txs |= pay._pt_transfer_get_linked_transactions()
        if all_txs:
            all_txs.write(
                {
                    "transfer_state": "pending",
                    "transfer_payment_id": False,
                }
            )
        return super().unlink()
