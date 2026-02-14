{
    'name': "POS OCA Promociones",
    'summary': """Prueba de concepto: Promociones basadas en datos de tarjeta para POS OCA""",
    'description': """
        Módulo de prueba de concepto para implementar promociones en pagos OCA.
        
        Este módulo extiende odoo_pos_oca para:
        - Capturar datos de tarjeta antes de autorizar (Acquirer, Issuer, CardNumber)
        - Aplicar descuentos basados en tipo de tarjeta
        - Agregar líneas de descuento a las órdenes POS
        - Confirmar transacciones con montos modificados
        
        Basado en la documentación POSLink v135, sección 3.2 - Venta simple (con promociones)
    """,
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'POS OCA',
    'version': '17.0.2.0.0',
    'depends': ['odoo_pos_oca', 'point_of_sale', 'payment', 'sale', 'loyalty'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_method_promotion_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'odoo_pos_oca_promociones/static/**/*',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}

