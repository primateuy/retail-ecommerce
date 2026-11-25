from odoo import fields, models


class ResConfigSettings(models.TransientModel):
	"""Expone la habilitacion del control de monto maximo FE en los ajustes del POS."""

	_inherit = 'res.config.settings'

	# El prefijo pos_ hace que el valor se escriba sobre el pos.config elegido.
	pos_ui_limit_enabled = fields.Boolean(
		related='pos_config_id.ui_limit_enabled',
		readonly=False,
	)
