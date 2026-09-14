{
    "name": "POS Forum - Order Search Expand",
    "summary": "Show all orders and reprint change ticket",
    "description": """
        Quita filtros de PDV/compañía en la búsqueda de órdenes del POS
        y agrega botón para reimprimir ticket de cambio desde órdenes.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.1.0",
    "depends": [
        "point_of_sale",
        "odoo_pos_oca",
    ],
    "data": [],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_order_search_expand/static/src/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
