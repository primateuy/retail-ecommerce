# -*- coding: utf-8 -*-
{
    'name': "Shopping Webservices",

    'summary': "Integración para el registro de ventas en Shoppings",

    'description': """

    """,

    'author': "Avance Software",
    'website': "https://avancesoftware.us/",

    'category': 'Accounting',
    'version': '0.2',

    
    'depends': ['base', 'web', 'l10n_uy', 'account', 'account_accountant', 'sale_management', 'loyalty', 'payment', 'point_of_sale'],

    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
        'views/account_journal.xml',
        'views/loyalty_program.xml',
        'views/shopping_payment_method.xml',
        'views/account_move.xml',
        'views/message_wizard.xml',
        'views/ventas_log.xml',
        'views/payment_method.xml',
        'views/pos_payment_method.xml',
        'views/payment_transaction.xml',
        'data/ir_cron.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'shopping_webservices/static/src/js/*',
        ],
    },
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}

