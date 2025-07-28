{
    'name': "POS INTEGRACION OCA",
    'summary': """POS INTEGRACION OCA""",
    'description': """POS INTEGRACION OCA""",
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Localization',
    'version': '17.0.1.0',
    'depends': ['base', 'point_of_sale', 'payment', 'account_payment', 'account_accountant'],
    'data': [
        'security/ir.model.access.csv',
        'data/oca_installation_data.xml',
        'views/pos_payment_method_views.xml',
        'views/pos_payment_views.xml',
        'views/payment_transaction_views.xml',
        'views/account_payment_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'odoo_pos_oca/static/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
}
