# -*- coding: utf-8 -*-
"""
Sincronización del estado funcional en payment.transaction cuando cambia el
estado del asiento de un pago (`account.payment` hereda de `account.move`).
"""

from odoo import models


class AccountMove(models.Model):
    """
    Detecta cuando un asiento ligado a un `account.payment` deja de estar
    publicado o se cancela, para devolver las transacciones de pago asociadas
    al estado «Pendiente».
    """

    _inherit = "account.move"

    def write(self, vals):
        """
        Tras actualizar el asiento, si pasó de publicado a otro estado y el
        movimiento pertenece a un pago, se revierte el estado en las transacciones.

        :param vals: dict de campos escritos en `account.move`.
        :return: resultado del `write` estándar.
        """
        # Bloque: solo nos interesan cambios de estado sobre movimientos ya publicados.
        if "state" not in vals or vals.get("state") == "posted":
            return super().write(vals)

        # Bloque: asientos publicados con al menos un `account.payment` (evita ruido en facturas, etc.).
        moves_was_posted = self.filtered(
            lambda m: m.state == "posted" and m.payment_ids
        )
        res = super().write(vals)
        # Bloque: movimientos que dejan de estar publicados y tienen pago vinculado.
        to_sync = moves_was_posted.filtered(lambda m: m.state != "posted").mapped(
            "payment_ids"
        )
        if to_sync:
            to_sync._pt_transfer_revert_linked_transactions_state()
        return res
