from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
	"""Habilita la declaración de ventas al shopping por diario.

	Los datos de conexión, contrato y secuencial pertenecen a la sucursal DGI
	del diario: varios diarios de la misma sucursal comparten contrato y el
	shopping exige un secuencial único por contrato. Los campos se exponen
	como relacionados editables para no cambiar a quienes los consumen.
	"""

	_inherit = 'account.journal'

	integracionShopping = fields.Boolean(string="Integración con Shopping", default=False)
	tecnologia = fields.Selection(
		related='dgi_sucursal_id.shopping_technology', readonly=False,
	)
	url = fields.Char(related='dgi_sucursal_id.shopping_url', readonly=False)
	usuario = fields.Char(related='dgi_sucursal_id.shopping_user', readonly=False)
	password = fields.Char(related='dgi_sucursal_id.shopping_password', readonly=False)
	homologacion = fields.Boolean(
		related='dgi_sucursal_id.is_shopping_homologation', readonly=False,
	)
	codigoShopping = fields.Char(related='dgi_sucursal_id.shopping_code', readonly=False)
	nroContrato = fields.Char(related='dgi_sucursal_id.shopping_contract_number', readonly=False)
	codigoCanal = fields.Char(related='dgi_sucursal_id.shopping_channel_code', readonly=False)
	caja = fields.Char(related='dgi_sucursal_id.shopping_cash_register', readonly=False)
	codigoRubro = fields.Char(related='dgi_sucursal_id.shopping_category_code', readonly=False)
	secuencial_ventas = fields.Integer(
		related='dgi_sucursal_id.shopping_sales_sequence', readonly=False,
	)
	shopping_payment_method_ids = fields.Many2many(
		related='dgi_sucursal_id.shopping_payment_method_ids', readonly=False,
	)

	@api.constrains(
		'integracionShopping', 'dgi_sucursal_id', 'tecnologia', 'url', 'password',
		'codigoShopping', 'nroContrato', 'codigoCanal',
	)
	def _check_shopping_integration(self):
		"""Valida que el diario con integración tenga sucursal DGI configurada.

		Raises:
			ValidationError: si falta la sucursal DGI o alguno de los datos
				obligatorios del shopping en ella.
		"""
		for journal in self.filtered('integracionShopping'):
			if not journal.dgi_sucursal_id:
				raise ValidationError(_(
					"Para activar la integración con Shopping en el diario %s, "
					"debe asignarle una Sucursal DGI.",
					journal.display_name,
				))
			if not all((
				journal.codigoShopping, journal.nroContrato, journal.codigoCanal,
				journal.tecnologia, journal.url, journal.password,
			)):
				raise ValidationError(_(
					"Para activar la integración con Shopping, debe completar en la "
					"sucursal %s todos los campos requeridos: Código Shopping, Nro Contrato, "
					"Código Canal, Tecnología, URL y Password.",
					journal.dgi_sucursal_id.display_name,
				))
