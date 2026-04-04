# -*- coding: utf-8 -*-
# Powered by Kanak Infosystems LLP.
# © 2023 Kanak Infosystems LLP. (<https://www.kanakinfosystems.com>).

{
    'name': 'POS Receipt Print By QZ',
    'version': '17.0.1.0',
    'category': 'Point of Sale',
    'summary': 'This module allows POS receipt print directly to the printer using QZ | QZ Print | POS Receipt | Print QZ | QZ Report | QZ Receipt',
    'description': """
This module provides to print pos receipt from qz
====================================================================================
With this Odoo Module you can set the QZ printer configuration to print the POS receipt which is not the default functionality In Odoo. Easy to take POS Receipt print from QZ printer. This module allows to choose the print method for POS orders.

* Key Features

* Print entire order on one receipt.

* Get print receipt from your QZ Printer.

* Set the printer configuration.

    """,
    'license': 'OPL-1',
    'author': 'Kanak Infosystems LLP.',
    'images': ['static/description/banner.jpg'],
    'website': 'https://www.kanakinfosystems.com',
    'depends': ['point_of_sale'],
    'data': [
        'views/res_company_view.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_qz_printer/static/src/lib/jsrsasign-latest-all-min.js',
            'pos_qz_printer/static/src/lib/rsvp-3.1.0.min.js',
            'pos_qz_printer/static/src/lib/sha-256.min.js',
            'pos_qz_printer/static/src/lib/qz-tray.js',
            'pos_qz_printer/static/src/js/pos_receipt_print.js'
        ],
    },
    'sequence': 1,
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 30,
    'currency': 'EUR',
    'live_test_url': 'https://youtu.be/0vYQb9VDqC4',
}