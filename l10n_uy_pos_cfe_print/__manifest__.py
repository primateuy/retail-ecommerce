{
	'name': "Uruguay - PdV: imprimir CFE de Uruware",
	'summary': "El PdV descarga el PDF oficial del CFE (Uruware) en lugar del reporte de Odoo",
	'description': """
Al validar una venta facturada en el Punto de Venta, o al reimprimir la factura desde la
lista de pedidos, se descarga la representación impresa del CFE que devuelve Uruware
(formato A4 o rollo según el punto de emisión). Si el CFE no fue emitido, se mantiene
el PDF estándar de Odoo.
	""",
	'author': "Primate",
	'website': "https://primate.uy",
	'category': 'Sales/Point of Sale',
	'version': '19.0.1.0.2',
	'depends': [
		'l10n_uy_einvoice_uruware',
		'point_of_sale',
	],
	'assets': {
		'point_of_sale._assets_pos': [
			'l10n_uy_pos_cfe_print/static/src/app/account_move_service.js',
		],
	},
	'license': 'LGPL-3',
	'installable': True,
}
