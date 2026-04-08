# -*- coding: utf-8 -*-
"""
Extensión de payment.transaction para trazabilidad de transferencias internas.

Los valores se actualizan desde el asistente (`payment.transaction.transfer.wizard`)
al crear la transferencia, y desde `account.move` / `account.payment` cuando el
asiento deja de estar publicado o se elimina el pago.
"""

from odoo import fields, models


class PaymentTransaction(models.Model):
    """
    Agrega el vínculo con la transferencia interna (`account.payment`) y el estado
    funcional de ese vínculo (pendiente vs. contabilizado).

    Sirve para evitar incluir dos veces la misma transacción en el asistente
    mientras la transferencia interna siga publicada, y para mostrar en la UI
    el avance del proceso contable.
    """

    _inherit = "payment.transaction"

    # Bloque: pago contable que representa la transferencia interna creada por el asistente (extremo origen).
    transfer_payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Transferencia interna",
        copy=False,
        readonly=True,
        help=(
            "Transferencia interna creada desde el asistente para esta "
            "transacción."
        ),
    )
    # Bloque: estado funcional respecto a la transferencia interna (no confundir con `state` del payment provider).
    transfer_state = fields.Selection(
        selection=[
            ("pending", "Pendiente"),
            ("posted", "Contabilizado"),
        ],
        string="Estado de transferencia",
        default="pending",
        required=True,
        copy=False,
        index=True,
        help=(
            "Pendiente: la transacción aún no quedó transferida o su "
            "transferencia fue revertida. Contabilizado: la transferencia "
            "interna asociada está publicada."
        ),
    )
