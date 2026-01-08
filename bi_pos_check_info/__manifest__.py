# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    'name': 'POS Cheque Information',
    'version': '17.0.0.1',
    'category': 'Point of Sale',
    'summary': 'Pos check information on pos cheque info on point of sale cheque details point of sales check information on receipt in pos cheque number on pos receipt check info pos order receipt cheque info pos payment cheque info point of sales cheque',
    'description': """The Point of Sale Check Info odoo app helps users to manage crucial information related to checks like the bank, customer name, account number, and check number within point of sale operations for businesses that accept check payments. It ensures efficient check management from point of sale.""",
    'author': 'BROWSEINFO',
    'website': 'https://www.browseinfo.com/demo-request?app=bi_pos_check_info&version=17&edition=Community',
    "price": 20,
    "currency": 'EUR',
    'depends': ['base', 'sale', 'point_of_sale'],
    'data': [
        'views/pos_config_view.xml',
        'views/pos_payment_method_view.xml',
        'views/pos_order_view.xml',
        'views/account_journal_view.xml',
    ],
    'demo': [],
    'test': [],
    'license': 'OPL-1',
    'assets': {
        'point_of_sale._assets_pos': [
            'bi_pos_check_info/static/src/js/models.js',
            'bi_pos_check_info/static/src/js/posStore.js',
            'bi_pos_check_info/static/src/js/paymentlines.js',
            'bi_pos_check_info/static/src/js/check_info_popup.js',
            'bi_pos_check_info/static/src/xml/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'live_test_url': 'https://www.browseinfo.com/demo-request?app=bi_pos_check_info&version=17&edition=Community',
    "images": ['static/description/POS-Check-Info.gif'],
}
