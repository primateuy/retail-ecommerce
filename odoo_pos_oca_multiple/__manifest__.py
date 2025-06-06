{
    'name': "POS INTEGRACION OCA MULTIPLE",
    'summary': """POS INTEGRACION OCA MULTIPLE""",
    'description': """POS INTEGRACION OCA MULTIPLE""",
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Localization',
    'version': '17.0.0.0',
    'depends': ['odoo_pos_oca', 'payment'],
    'data': [
        'security/ir.model.access.csv',
        'data/payment_provider_data.xml',
        'views/payment_provider_views.xml',
        'views/pos_payment_method_views.xml',
    ],
    'license': 'LGPL-3',
}
