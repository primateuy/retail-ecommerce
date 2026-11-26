from odoo import fields, models


class PosConfig(models.Model):
	"""Caja del PdV: uso de la factura de Uruware en lugar de la de Odoo."""

	_inherit = 'pos.config'

	download_invoice_fe = fields.Boolean(
		string="Descargar factura FE",
		default=True,
		help="Si está activo, la descarga de la factura al validar, el botón de factura de "
		"la lista de órdenes, el recibo de la pantalla de pago e «Imprimir recibo completo» "
		"usan el PDF del CFE de Uruware. Si no, el PdV se comporta como Odoo estándar.",
	)
