# -*- coding: utf-8 -*-
"""
Extensión de payment.transaction para el flujo POS Fiserv ITD.

Aporta los Many2one a pos.order / pos.payment y la sincronización del
``payment_transaction_id`` en pos.payment. Estos campos no pueden vivir en
``odoo_pos_fiserv_core`` porque el core no depende de point_of_sale.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Pedido POS',
        ondelete='set null',
        help='Pedido del punto de venta que generó la transacción.',
    )
    pos_payment_id = fields.Many2one(
        'pos.payment',
        string='Pago POS',
        ondelete='set null',
        help='Pago del punto de venta que generó la transacción.',
    )

    def write(self, vals):
        """
        Sincroniza ``pos.payment.payment_transaction_id`` cuando cambia el
        ``pos_payment_id`` de la transacción. La sincronización con
        ``account.payment`` vive en el core (no requiere POS).
        """
        if 'pos_payment_id' in vals:
            old_payment_id = self.pos_payment_id.id if self.pos_payment_id else False
            new_payment_id = vals['pos_payment_id']
            if old_payment_id:
                old_payment = self.env['pos.payment'].browse(old_payment_id)
                if old_payment.exists() and 'payment_transaction_id' in old_payment._fields:
                    old_payment.payment_transaction_id = False
            if new_payment_id:
                new_payment = self.env['pos.payment'].browse(new_payment_id)
                if new_payment.exists() and 'payment_transaction_id' in new_payment._fields:
                    new_payment.payment_transaction_id = self.id
        return super().write(vals)

    def update_payment_transaction_reference(self):
        """
        Actualiza ``pos.payment.payment_transaction_id`` para mantener la
        referencia bidireccional entre pago POS y transacción Fiserv.
        """
        for transaction in self:
            if transaction.pos_payment_id and 'payment_transaction_id' in transaction.pos_payment_id._fields:
                transaction.pos_payment_id.payment_transaction_id = transaction.id
                _logger.info(
                    'Campo payment_transaction_id actualizado en pago %s para transacción %s',
                    transaction.pos_payment_id.name,
                    transaction.fiserv_transaction_id,
                )
