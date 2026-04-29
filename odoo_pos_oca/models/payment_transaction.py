# -*- coding: utf-8 -*-
"""
Extensión de payment.transaction para el flujo POS OCA.

Aporta los campos ``pos_order_id`` / ``pos_payment_id`` y los hooks que
sincronizan con ``pos.payment``. Vive aquí (no en odoo_pos_oca_core) para que
el core no arrastre dependencia de point_of_sale: el core es el sustrato
compartido entre POS y backend contable.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Pedido POS',
        help='Pedido del punto de venta que generó la transacción',
    )

    pos_payment_id = fields.Many2one(
        'pos.payment',
        string='Pago POS',
        help='Pago del punto de venta que generó la transacción',
    )

    def write(self, vals):
        """
        Mantiene en sincronía ``pos.payment.payment_transaction_id`` cuando
        cambia ``pos_payment_id`` en la transacción. Limpia el campo del pago
        anterior y lo vuelve a setear en el nuevo, asegurando referencia
        bidireccional única.
        """
        if 'pos_payment_id' in vals:
            new_payment_id = vals['pos_payment_id']
            for tx in self:
                old_payment = tx.pos_payment_id
                if old_payment and old_payment.id != new_payment_id:
                    if old_payment.exists():
                        old_payment.payment_transaction_id = False
                if new_payment_id:
                    new_payment = self.env['pos.payment'].browse(new_payment_id)
                    if new_payment.exists():
                        new_payment.payment_transaction_id = tx.id
        return super().write(vals)

    def update_payment_transaction_reference(self):
        """
        Refuerza la referencia bidireccional pago POS ↔ transacción.

        Se llama desde flujos donde la transacción se vinculó al pos.payment a
        posteriori (por ejemplo, asociación diferida tras crear la orden POS).
        """
        for transaction in self:
            if transaction.pos_payment_id:
                transaction.pos_payment_id.payment_transaction_id = transaction.id
                _logger.info(
                    'Campo payment_transaction_id actualizado en pago %s para transacción %s',
                    transaction.pos_payment_id.name,
                    transaction.oca_transaction_id,
                )
