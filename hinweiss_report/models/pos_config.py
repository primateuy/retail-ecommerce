# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
	"""Extiende pos.config con el código de caja utilizado por Hinweiss.

	Agrega el campo codigo_caja_hinweiss, utilizado para identificar
	el punto de venta en los reportes generados para Hinweiss.
	"""

	_inherit = "pos.config"

	codigo_caja_hinweiss = fields.Char(
		string="Código de Caja Hinweiss",
		help="Código de caja utilizado para identificar este punto de venta en los reportes de Hinweiss.",
	)
