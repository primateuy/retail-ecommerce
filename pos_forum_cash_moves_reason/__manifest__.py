{
    "name": "POS Forum - Cash Move Reasons",
    "summary": "Cash in/out reasons in POS by config",
    "description": """
        Extiende el POS para solicitar razones de entradas/salidas de efectivo
        configuradas por punto de venta y enviarlas al backend.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "point_of_sale",
        "pos_cash_move_reason",
    ],
    "data": [
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_cash_moves_reason/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
