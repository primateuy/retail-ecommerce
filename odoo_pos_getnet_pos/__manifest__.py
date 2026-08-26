# -*- coding: utf-8 -*-
{
    "name": "Getnet TransAct - POS",
    "summary": "Cobro con terminal Getnet/TransAct desde el punto de venta.",
    "description": """
Flujo TPV de la integración Getnet/TransAct v4: pos.payment.method con
terminal 'getnet', posteo y polling en el servidor (mismo motor y lock por
terminal del core), resolución de la línea de pago por bus
(GETNET_LATEST_RESPONSE) y asociación transacción-orden por referencia
con fallback por monto.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Sales/Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "odoo_pos_getnet_core",
        "point_of_sale",
    ],
    "data": [
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "odoo_pos_getnet_pos/static/src/app/**/*",
            "odoo_pos_getnet_pos/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
}
