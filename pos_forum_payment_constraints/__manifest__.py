{
    "name": "POS Forum - Payment Constraints",
    "summary": "Readonly opening/closing and cash closing cap",
    "description": """
        Agrega controles por método de pago para apertura/cierre y tope de saldo en efectivo.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "point_of_sale",
    ],
    "data": [
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_payment_constraints/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
