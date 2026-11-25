from odoo import api, fields, models


class ResPartner(models.Model):
	"""Monto maximo permitido por comprobante FE para ventas del POS."""

	_inherit = 'res.partner'

	# Mismos nombres que en pos_forum_customer_ui v17 (#4732) para que la
	# configuracion de los contactos pueda conservarse al migrar.
	pos_fe_amount_limit_control = fields.Boolean(
		string="Control de monto máximo permitido FE",
		help="Habilita el control de un monto máximo permitido por comprobante "
		"de facturación electrónica para este cliente en el POS.",
	)
	pos_fe_max_amount_currency_id = fields.Many2one(
		'res.currency',
		string="Moneda monto total",
		help="Moneda en la que se expresa el monto máximo, por ejemplo UYI.",
	)
	pos_fe_max_amount = fields.Monetary(
		string="Monto total permitido (sin IVA)",
		currency_field='pos_fe_max_amount_currency_id',
		help="Se compara contra el total de la venta sin IVA, como mide DGI el "
		"límite de 5.000 UI para e-Tickets sin receptor.",
	)
	pos_fe_company_currency_id = fields.Many2one(
		'res.currency',
		string="Moneda compañía",
		compute='_compute_pos_fe_max_amount_company_currency',
	)
	# Sin store a proposito: en v17 era stored y dependia de las cotizaciones, lo
	# que obligaba a recomputar contactos cada vez que el cron del BCU cargaba una.
	# Solo se muestra en la ficha; el POS convierte al momento de controlar.
	pos_fe_max_amount_company_currency = fields.Monetary(
		string="Monto total moneda compañía (sin IVA)",
		compute='_compute_pos_fe_max_amount_company_currency',
		currency_field='pos_fe_company_currency_id',
	)

	@api.depends_context('company')
	@api.depends('pos_fe_max_amount', 'pos_fe_max_amount_currency_id')
	def _compute_pos_fe_max_amount_company_currency(self):
		"""Muestra el monto maximo convertido a la moneda de la compania a hoy."""
		company = self.env.company
		for partner in self:
			partner.pos_fe_company_currency_id = company.currency_id
			partner.pos_fe_max_amount_company_currency = partner._get_pos_fe_max_amount_in(
				company.currency_id, company,
			)

	@api.onchange('pos_fe_amount_limit_control')
	def _onchange_pos_fe_amount_limit_control(self):
		"""Propone la moneda de la compania al activar el control, como en v17."""
		for partner in self:
			if partner.pos_fe_amount_limit_control and not partner.pos_fe_max_amount_currency_id:
				partner.pos_fe_max_amount_currency_id = self.env.company.currency_id

	def _get_pos_fe_max_amount_in(self, currency, company):
		"""Convierte el monto maximo FE del contacto a otra moneda con la cotizacion de hoy.

		Args:
			currency (res.currency): Moneda destino.
			company (res.company): Compania cuyas cotizaciones se usan.

		Returns:
			float: Monto maximo expresado en `currency`.
		"""
		self.ensure_one()
		source = self.pos_fe_max_amount_currency_id
		if not source:
			return self.pos_fe_max_amount
		return source._convert(
			self.pos_fe_max_amount, currency, company, fields.Date.context_today(self),
		)
