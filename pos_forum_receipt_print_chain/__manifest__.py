# -*- coding: utf-8 -*-
{
    "name": "POS Forum — Recibo y ticket de cambio en un clic",
    "summary": "Al pulsar Imprimir en el recibo, imprime el ticket de venta y el ticket de cambio.",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "author": "Forum Primate",
    "license": "LGPL-3",
    "depends": [
        "odoo_pos_no_invoice",
        "odoo_pos_oca",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_receipt_print_chain/static/src/js/receipt_screen_print_chain.js",
        ],
    },
    "installable": True,
    "application": False,
}
