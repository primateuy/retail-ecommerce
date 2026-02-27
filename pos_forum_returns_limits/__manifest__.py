{
    "name": "POS Forum - Returns Limits",
    "summary": "Limit refunds by days on POS",
    "description": """
        Agrega un límite de días para devoluciones configurado por POS.
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
            "pos_forum_returns_limits/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
