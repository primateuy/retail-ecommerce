{
	'name': "Uruguay - PdV: imprimir CFE de Uruware",
	'summary': "El PdV descarga el PDF oficial del CFE (Uruware) en lugar del reporte de Odoo",
	'description': """
Con «Descargar factura FE» activo en la caja (Ajustes del PdV, activo por defecto), el PdV
usa la representación impresa del CFE que devuelve Uruware (A4 o rollo según el punto de
emisión) en lugar de la factura y el recibo de Odoo:

- Descarga de la factura al validar la venta y botón de factura de la lista de pedidos.
- Recibo de la pantalla de pago exitoso.
- «Imprimir recibo completo».

Se reutiliza el PDF que la localización guarda al firmar el CFE. Si el CFE no fue emitido se
mantiene lo estándar de Odoo; si Uruware no devuelve el PDF, el PdV avisa al cajero y sigue
(la factura se reimprime desde Órdenes). Con el check desactivado, el PdV se comporta como
Odoo estándar.
	""",
	'author': "Primate",
	'website': "https://primate.uy",
	'category': 'Sales/Point of Sale',
	'version': '19.0.1.3.0',
	'depends': [
		'l10n_uy_einvoice_uruware',
		'point_of_sale',
	],
	'data': [
		'views/res_config_settings_views.xml',
	],
	'assets': {
		'point_of_sale._assets_pos': [
			'l10n_uy_pos_cfe_print/static/src/app/**/*',
		],
	},
	'license': 'LGPL-3',
	'installable': True,
}
