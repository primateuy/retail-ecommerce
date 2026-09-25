{
    "name": "POS Forum - Order Search Expand",
    "summary": "Show all orders and reprint change ticket",
    "description": """
        Quita filtros de PDV/compañía en la búsqueda de órdenes del POS,
        agrega el campo de búsqueda "Todo" (nº de orden, nº de recibo y cliente),
        normaliza el nº de orden leído del ticket de cambio en cualquier pantalla
        (Órdenes y Reembolso) y agrega botón para reimprimir ticket de cambio.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.3.0",
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
