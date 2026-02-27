{
    "name": "POS Forum - Payment Default Customer",
    "summary": "Default customer when going to payment screen",
    "description": """
        Aplica un cliente por defecto al momento de pasar a la pantalla de pago
        si la orden no tiene cliente asignado. Compatible con bi_pos_default_customer
        (cliente por defecto al crear orden); este módulo solo actúa al entrar a pagar.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "point_of_sale",
    ],
    "data": [
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_payment_default_customer/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
