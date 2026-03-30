# -*- coding: utf-8 -*-
{
    'name': 'Loyalty Customer Domain POS',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Extends customer domain loyalty rules to POS using fields available in the POS session.',
    'description': (
        'Loads customer domain rules into POS and blocks rewards when the selected '
        'customer does not match the rule domain evaluated with fields available in POS.'
    ),
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'pos_loyalty', 'loyality_customer_domain'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            'loyalty_customer_domain_pos_fixed/static/src/js/loyalty_customer_domain_pos.js',
        ],
    },
    'installable': True,
    'application': False,
}
