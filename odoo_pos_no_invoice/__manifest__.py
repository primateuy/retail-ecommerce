{
    'name': "ODOO POS NO INVOICE",
    'summary': """No descargar la factura en el POS""",
    'description': """No descargar la factura en el POS""",
    'category': 'Localization',
    'version': '17.0.0.0',
    'depends': ['base', 'point_of_sale'],
    'data': [
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'odoo_pos_no_invoice/static/**/*',
        ],
    },
    'license': 'LGPL-3',
}
