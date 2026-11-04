{
	'name': 'Shopping Webservices - POS Manual',
	'version': '17.0.1.0.0',
	'author': 'PrimateUY',
	'website': 'https://primate.uy',
	'category': 'Point of Sale',
	'license': 'AGPL-3',
	'summary': """Muestra el Código Shopping en el bloque POS Manual de la transacción.""",
	'description': """
Módulo puente entre shopping_webservices y pos_forum_manual_payment.

En las transacciones POS Manual el Código Shopping se muestra dentro del
bloque «POS Manual», debajo del Sello, en lugar de en los datos generales.
Se instala solo cuando ambos módulos están instalados.
""",
	'depends': [
		'pos_forum_manual_payment',
		'shopping_webservices',
	],
	'data': [
		# VISTAS
		'views/payment_transaction_views.xml',
	],
	'auto_install': True,
	'installable': True,
	'application': False,
}
