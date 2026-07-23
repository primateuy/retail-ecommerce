# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
	"""Extiende pos.config con el código de caja utilizado por Hingweiss.

	Agrega el campo codigo_caja_higweiss, utilizado para identificar
	el punto de venta en los reportes generados para Hingweiss.
	"""

	_inherit = "pos.config"

	codigo_caja_higweiss = fields.Char(
		string="Código de Caja Hingweiss",
		help="Código de caja utilizado para identificar este punto de venta en los reportes de Hingweiss.",
	)
