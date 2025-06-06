{
    'name': "POS INTEGRACION OCA",
    'summary': """POS INTEGRACION OCA""",
    'description': """POS INTEGRACION OCA""",
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Localization',
    'version': '17.0.0.0',
    'depends': ['base', 'point_of_sale'],
    'data': [
        'views/pos_payment_method_views.xml',
        'views/pos_payment_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'odoo_pos_oca/static/**/*',
        ],
    },
    'license': 'LGPL-3',
}
