{
    "name": "POS Forum - Salesperson Required",
    "summary": "Order salesperson and mandatory line salesperson",
    "description": """
        Agrega vendedor a nivel de orden y exige vendedor en líneas antes de pagar.
        Integra el módulo pw_pos_salesperson_emp para heredar el vendedor de la orden.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "point_of_sale",
        "hr",
        "pw_pos_salesperson_emp",
    ],
    "data": [
        "views/pos_order_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_salesperson_required/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
