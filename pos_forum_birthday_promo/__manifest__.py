# -*- coding: utf-8 -*-
{
    "name": "POS Forum - Promoción cumpleaños",
    "summary": "Descuento por cumpleaños en POS con ventana de días, línea de "
    "producto y reward de lealtad (trazabilidad).",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "author": "PRIMATE",
    "website": "https://www.primateuy.com",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "pos_loyalty",
        "partner_contact_birthdate",
    ],
    "data": [
        "data/product_data.xml",
        "data/loyalty_init.xml",
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_birthday_promo/static/src/js/birthday_promo_service.js",
        ],
    },
    "installable": True,
    "application": False,
}
