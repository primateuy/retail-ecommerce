from odoo import models


class PosPayment(models.Model):
	"""Recalcula la distribución shopping cuando el pago recibe su transacción."""

	_inherit = 'pos.payment'

	def write(self, vals):
		"""Al enlazar payment_transaction_id, rehace la distribución de la factura.

		Args:
			vals (dict): valores a escribir.

		Returns:
			bool: resultado de super().write.
		"""
		result = super().write(vals)
		if vals.get('payment_transaction_id'):
			self.mapped('pos_order_id')._refresh_shopping_payment_distribution()
		return result
