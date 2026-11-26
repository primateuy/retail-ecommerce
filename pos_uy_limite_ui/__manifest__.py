{
	"name": "POS UY - Limite de monto FE por cliente",
	"summary": "Bloquea en el POS las ventas que superan el monto maximo FE del cliente",
	"description": """
		Cada contacto puede tener un control de monto maximo permitido por
		comprobante de facturacion electronica (pestana "Control FE"), por ejemplo
		5.000 UI para el Consumidor Final. El POS bloquea el paso a pago y la
		validacion cuando el total de la venta supera ese monto, para que se
		identifique al cliente antes de cobrar. Si la venta no tiene cliente se
		controla el cliente por defecto del punto de venta.
	""",
	"author": "PRIMATE",
	"website": "https://www.primateuy.com",
	"category": "Point of Sale",
	"version": "19.0.1.0.0",
	"depends": [
		"point_of_sale",
		"l10n_uy_einvoice_base",
	],
	"data": [
		"views/res_config_settings_views.xml",
		"views/res_partner_views.xml",
	],
	"assets": {
		"point_of_sale._assets_pos": [
			"pos_uy_limite_ui/static/src/**/*",
		],
	},
	"license": "LGPL-3",
	"installable": True,
	"application": False,
}
