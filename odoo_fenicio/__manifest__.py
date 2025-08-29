# -*- coding: utf-8 -*-
{
    'name': "INTEGRACION FENICIO",
    'summary': """INTEGRACION FENICIO""",
    'description': """INTEGRACION FENICIO""",
    'category': 'Localization',
    'version': '17.0.0.0',
    'depends': ['base', 'sale', 'sale_management', 'account', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_attribute_views.xml',
        'views/product_template_views.xml',
        'views/product_product_easy_form.xml',
        'views/account_payment_term_views.xml',
        'views/account_payment_views.xml',
        'views/sale_views.xml',
        'data/data.xml',
        # 'data/payments_diaries.xml',
    ],
    'license': 'LGPL-3',
}
