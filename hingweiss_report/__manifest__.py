{
	'name': 'Hingweiss Report',
	'version': '17.0.1.0.0',
	'author': 'PrimateUY',
	'website': 'https://primate.uy',
	'category': 'Point of Sale',
	'license': 'AGPL-3',
	'summary': """Agrega el código de caja Hingweiss al punto de venta.""",
	'description': """
		Extiende pos.config con el campo codigo_caja_higweiss, utilizado
		para identificar el punto de venta en los reportes generados
		para Hingweiss.
	""",
	'depends': [
		'point_of_sale',
	],
	'data': [
		'views/pos_config_views.xml',
	],
	'auto_install': False,
	'installable': True,
	'application': False,
}
