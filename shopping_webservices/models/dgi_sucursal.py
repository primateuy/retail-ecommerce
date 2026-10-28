from odoo import fields, models


class DgiSucursal(models.Model):
	"""Datos de integración con el webservice del shopping por sucursal DGI.

	El shopping identifica al locatario por contrato y numera las
	declaraciones con un único secuencial por contrato. Como varios diarios
	pueden emitir CFE desde la misma sucursal, los datos viven acá y los
	diarios los exponen como campos relacionados.
	"""

	_inherit = 'dgi.sucursal'

	shopping_technology = fields.Selection(
		[
			('lecueder', "Lecueder"),
			('costa_urbana', "Costa Urbana"),
		],
		string="Tecnología",
		default='lecueder',
	)
	shopping_url = fields.Char(
		string="URL",
		help="URL del servicio web proporcionado por el shopping para la integración.",
	)
	shopping_user = fields.Char(
		string="Usuario",
		help="Usuario para autenticar en el servicio web del shopping.",
	)
	shopping_password = fields.Char(
		string="Password",
		help="Contraseña para autenticar en el servicio web del shopping.",
	)
	is_shopping_homologation = fields.Boolean(string="Modo Homologación", default=False)
	shopping_code = fields.Char(
		string="Código Shopping",
		help="Código asignado por el shopping para identificar este punto de venta.",
	)
	shopping_contract_number = fields.Char(
		string="Nro Contrato",
		help="Número de contrato asociado a este punto de venta en el shopping.",
	)
	shopping_channel_code = fields.Char(
		string="Código Canal",
		help="Código del canal de ventas asignado por el shopping.",
	)
	shopping_cash_register = fields.Char(
		string="Caja",
		help="Identificador de la caja registradora asociada a este punto de venta.",
	)
	shopping_category_code = fields.Char(
		string="Código Rubro",
		help="Código de rubro asignado por el shopping para este punto de venta.",
	)
	shopping_sales_sequence = fields.Integer(
		string="Secuencial Ventas",
		default=0,
		help="Secuencial de declaraciones enviadas al shopping. Es único por contrato, "
		"por eso se comparte entre todos los diarios de la sucursal.",
	)
	shopping_payment_method_ids = fields.Many2many(
		'shopping.payment.method',
		'dgi_sucursal_shopping_payment_rel',
		'dgi_sucursal_id',
		'payment_method_id',
		string="Formas de Pago Shopping",
	)
