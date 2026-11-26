from odoo import api, fields, models
from odoo.tools.misc import formatLang

# Campos de cliente por defecto del POS segun el modulo instalado:
# bi_pos_default_customer (v19) y pos_forum_payment_default_customer (Forum v17).
DEFAULT_CUSTOMER_FIELDS = ('res_partner_id', 'payment_default_customer_id')


class PosOrder(models.Model):
	"""Control del monto maximo FE del cliente para ventas del POS."""

	_inherit = 'pos.order'

	@api.model
	def get_fe_amount_limit_requirement(self, config_id, partner_id, amount_untaxed):
		"""Indica si la venta supera el monto maximo FE del cliente y debe bloquearse.

		Lo llama el POS al pasar a pago y al validar. Se controla el cliente del
		pedido o, si no tiene, el cliente por defecto del punto de venta. Solo
		aplica a contactos con el control activo en la pestana "Control FE".

		Args:
			config_id (int): ID del pos.config donde se vende.
			partner_id (int|bool): ID del cliente del pedido, o False si no tiene.
			amount_untaxed (float): Total del pedido sin impuestos, en la moneda del POS.

		Returns:
			dict: blocked (bool), title (str) y message (str).
		"""
		config = self.env['pos.config'].browse(config_id)
		result = {'blocked': False, 'title': '', 'message': ''}
		if not config.ui_limit_enabled:
			return result
		partner = self._get_fe_limit_partner(config, partner_id)
		if not partner.pos_fe_amount_limit_control:
			return result

		company = config.company_id
		today = fields.Date.context_today(self)
		amount_company = abs(config.currency_id._convert(
			amount_untaxed, company.currency_id, company, today,
		))
		limit_company = partner._get_pos_fe_max_amount_in(company.currency_id, company)
		if amount_company <= limit_company:
			return result

		# Se muestra el limite en la moneda cargada en la ficha y con su codigo
		# (ej. UYI 5.000,00): el simbolo de la UYI suele ser "$" y confunde.
		limit_currency = partner.pos_fe_max_amount_currency_id or company.currency_id
		limit_label = "%s %s" % (
			limit_currency.name,
			formatLang(self.env, partner.pos_fe_max_amount, digits=limit_currency.decimal_places),
		)
		result.update({
			'blocked': True,
			'title': self.env._("PURCHASE OVER %(limit)s", limit=limit_label),
			'message': self.env._(
				"The sale total without VAT is over %(limit)s. The customer must be "
				"identified: select a customer with a valid document.",
				limit=limit_label,
			),
		})
		return result

	@api.model
	def _get_fe_limit_partner(self, config, partner_id):
		"""Devuelve el contacto a controlar: el del pedido o el por defecto del POS.

		Args:
			config (pos.config): Punto de venta del pedido.
			partner_id (int|bool): ID del cliente del pedido.

		Returns:
			res.partner: Contacto a controlar (puede estar vacio).
		"""
		if partner_id:
			return self.env['res.partner'].browse(partner_id)
		for field_name in DEFAULT_CUSTOMER_FIELDS:
			if field_name in config._fields and config[field_name]:
				return config[field_name]
		return self.env['res.partner']
