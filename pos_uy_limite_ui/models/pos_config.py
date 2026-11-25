from odoo import fields, models


class PosConfig(models.Model):
	"""Habilitacion por punto de venta del control de monto maximo FE."""

	_inherit = 'pos.config'

	ui_limit_enabled = fields.Boolean(
		string="Control monto maximo FE",
		default=True,
		help="Bloquea el cobro cuando el total supera el monto maximo FE del cliente.",
	)
