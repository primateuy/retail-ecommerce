# -*- coding: utf-8 -*-
"""Extensión de loyalty.program para el ticket de cupón de próxima compra."""

from odoo import fields, models


class LoyaltyProgram(models.Model):
	"""Configuración del mensaje editable del ticket de próxima compra.

	El encabezado del ticket es fijo (lo define el reporte QWeb); este modelo
	solo aporta la línea de alcance editable y el helper que formatea el
	descuento de la recompensa para inyectarlo en el ticket.
	"""

	_inherit = "loyalty.program"

	forum_receipt_scope = fields.Text(
		string="Alcance del cupón (ticket)",
		translate=True,
		help="Línea editable que se imprime bajo el encabezado del cupón de "
		"próxima compra. Sirve para aclarar el alcance del descuento "
		"(p. ej. una categoría de producto). Placeholders disponibles: "
		"{descuento} y {codigo}.",
	)

	def _forum_get_discount_display(self):
		"""Devuelve el descuento de la recompensa como texto para el ticket.

		Toma la primera recompensa de tipo descuento del programa. Para
		descuentos porcentuales devuelve ``"15%"``; para montos fijos antepone
		el símbolo de la moneda del programa.

		Returns:
			str: descuento formateado, o cadena vacía si el programa no tiene
				una recompensa de descuento.
		"""
		self.ensure_one()
		reward = self.reward_ids.filtered(
			lambda r: r.reward_type == "discount"
		)[:1]
		if not reward:
			return ""
		if reward.discount_mode == "percent":
			# "%g" evita el ".0" sobrante (15 en lugar de 15.0).
			return "%g%%" % reward.discount
		symbol = self.currency_id.symbol or ""
		return ("%s %g" % (symbol, reward.discount)).strip()

	def _forum_render_receipt_scope(self, coupon):
		"""Resuelve los placeholders de la línea de alcance del ticket.

		Args:
			coupon (loyalty.card): cupón concreto que se está imprimiendo, del
				que se toma el código para el placeholder ``{codigo}``.

		Returns:
			str: el texto de ``forum_receipt_scope`` con los placeholders
				reemplazados, o cadena vacía si no hay mensaje configurado.
		"""
		self.ensure_one()
		message = self.forum_receipt_scope or ""
		if not message:
			return ""
		# Reemplazo explícito (no str.format) para no romper ante llaves sueltas.
		return (
			message
			.replace("{descuento}", self._forum_get_discount_display())
			.replace("{codigo}", coupon.code or "")
		)