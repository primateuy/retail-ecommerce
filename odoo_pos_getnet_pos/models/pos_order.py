# -*- coding: utf-8 -*-
"""Asociación transacción Getnet <-> orden/pago POS y voucher."""

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _process_order(self, order, draft, existing_order):
        order_id = super()._process_order(order, draft, existing_order)
        try:
            self.browse(order_id)._getnet_associate_transactions()
        except Exception:
            # La asociación nunca debe romper el cobro ya realizado
            _logger.exception(
                'Getnet: fallo asociando transacciones a la orden %s.',
                order_id)
        return order_id

    def _getnet_associate_transactions(self):
        """
        Asocia por REFERENCIA (pos.payment.transaction_id == referencia de
        la payment.transaction, seteada por el JS al aprobar) y, solo si
        falta, fallback por monto más cercano entre las transacciones done
        del método sin orden asociada.
        """
        Tx = self.env['payment.transaction']
        for order in self:
            for payment in order.payment_ids:
                if payment.payment_method_id.use_payment_terminal != 'getnet':
                    continue
                tx = Tx.search([
                    ('reference', '=', payment.transaction_id),
                    ('provider_id.code', '=', 'getnet'),
                ], limit=1) if payment.transaction_id else Tx
                if not tx:
                    candidatas = Tx.search([
                        ('provider_id.code', '=', 'getnet'),
                        ('state', '=', 'done'),
                        ('getnet_pos_order_id', '=', False),
                        ('getnet_transaction_origin', '=', 'pos_payment'),
                    ], order='id desc', limit=20)
                    tx = candidatas.filtered(
                        lambda t: abs(t.amount - abs(payment.amount)) < 0.01
                    )[:1]
                if tx:
                    tx.write({
                        'getnet_pos_order_id': order.id,
                        'getnet_pos_payment_id': payment.id,
                    })

    def get_getnet_voucher(self):
        """Voucher persistido de la transacción de la orden (reimpresión)."""
        self.ensure_one()
        tx = self.env['payment.transaction'].search([
            ('getnet_pos_order_id', '=', self.id),
            ('state', '=', 'done'),
        ], order='id desc', limit=1)
        return {
            'voucher': tx.getnet_voucher or '',
            'ticket': tx.getnet_ticket or '',
            'reference': tx.reference or '',
        }
