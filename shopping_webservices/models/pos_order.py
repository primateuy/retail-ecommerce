import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_invoice(self, move_vals):
        new_move = super()._create_invoice(move_vals)

        if not new_move.journal_id.integracionShopping:
            return new_move

        distribution = self._build_shopping_payment_distribution(new_move.journal_id)
        if distribution:
            new_move.payment_distribution = json.dumps(distribution)
            _logger.info(
                'Shopping: payment_distribution generado para factura %s: %s',
                new_move.name or new_move.id, distribution
            )

        return new_move

    def _build_shopping_payment_distribution(self, journal):
        distribution = []

        contado_method = journal.shopping_payment_method_ids.filtered(
            lambda m: m.payment_type == 'contado'
        )[:1]

        for payment in self.payment_ids:
            if payment.amount <= 0:
                continue

            pos_method = payment.payment_method_id
            shopping_method = None

            # Primero: buscar por el código de la transacción (resuelve marca/emisor)
            # dentro de los métodos asignados al diario
            if payment.payment_transaction_id:
                tx_code = payment.payment_transaction_id.shopping_payment_code
                if tx_code:
                    shopping_method = journal.shopping_payment_method_ids.filtered(
                        lambda m: m.payment_code == tx_code
                    )[:1]

            # Segundo: si no hay transacción, usar el mapeo estático del método POS
            if not shopping_method and pos_method.is_pos_shopping and pos_method.shopping_payment_method_id:
                candidate = pos_method.shopping_payment_method_id
                if candidate in journal.shopping_payment_method_ids:
                    shopping_method = candidate

            # Fallback: contado
            if not shopping_method:
                if contado_method:
                    _logger.warning(
                        'Shopping: sin método para pago PDV %s (%s). Asignando Contado.',
                        payment.id, pos_method.name
                    )
                    shopping_method = contado_method
                else:
                    _logger.warning(
                        'Shopping: sin método para pago PDV %s (%s) y sin Contado en diario. Se omite.',
                        payment.id, pos_method.name
                    )
                    continue

            existing = next(
                (d for d in distribution if d['payment_method_id'] == shopping_method.id),
                None
            )
            if existing:
                existing['amount'] += payment.amount
            else:
                distribution.append({
                    'payment_method_id': shopping_method.id,
                    'amount': payment.amount,
                })

        return distribution
