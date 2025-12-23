# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    'name': 'POS Multi Currency Pricelist',
    'version': '17.0.0.9',
    'category': 'Point of Sale',
    'summary': 'Point of sale multi Currency pricelist allow multi currency pricelist on pos multiple currency pricelist pos multiple currencies pricelist allow multi currency pricelist on pos allow multi currency pricelist on point of sales pos multi pricelist on pos',
    'description' :"""
        The POS Multi-Currency Pricelist Odoo App helps the user to manage their point of sale processes in multiple currencies. This app simplifies the process of managing pricelists in different currencies, making it easier for businesses to sell products and services globally. Users can easily change the pricelist and the pos product price will change according to the selected pricelist currency, on the pos payment screen user also can see the price based on the selected pricelist currency.
    """,
    'author': 'BrowseInfo',
    'website': "https://www.browseinfo.com/demo-request?app=bi_pos_multi_currency_pricelist&version=17&edition=Community",
    "price": 49,
    "currency": 'EUR',
    'depends': ['base','point_of_sale'],
    'data': [
        # 'views/models_view.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'bi_pos_multi_currency_pricelist/static/src/app/modelsss.js',
            'bi_pos_multi_currency_pricelist/static/src/app/TicketScreen.js',
            'bi_pos_multi_currency_pricelist/static/src/app/OrderLine.js',
            'bi_pos_multi_currency_pricelist/static/src/app/pos_store.js',
            'bi_pos_multi_currency_pricelist/static/src/app/pricelist.js',
             (
            'replace', 'point_of_sale/static/src/app/utils/contextual_utils_service.js', 'bi_pos_multi_currency_pricelist/static/src/app/currency.js')
            
        ],
    },
    'demo': [],
    'license':'OPL-1',
    'test': [],
    'installable': True,
    'auto_install': False,
    'live_test_url':'https://www.browseinfo.com/demo-request?app=bi_pos_multi_currency_pricelist&version=17&edition=Community',
    "images":['static/description/Banner.gif'],
}
