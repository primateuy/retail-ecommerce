from odoo import fields, models


class ResConfigSettings(models.TransientModel):
	"""Expone en Ajustes del PdV la opción «Descargar factura FE» de la caja."""

	_inherit = 'res.config.settings'

	pos_download_invoice_fe = fields.Boolean(
		related='pos_config_id.download_invoice_fe',
		readonly=False,
	)
