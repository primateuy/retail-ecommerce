{
    "name": "Precio del producto en el PdV",
    "summary": "Muestra el precio de venta en la tarjeta de cada producto del PdV.",
    "description": """
Muestra el precio en la tarjeta de cada producto de la pantalla de productos del PdV.

El precio se calcula como en el popup de información del producto: con la lista de
precios y la posición fiscal de la orden actual, e incluye o no los impuestos según
la configuración de la caja (precios con impuestos incluidos / excluidos).

Basado en product_price_on_pos de HSxTECH (LGPL-3), corregido para v19: la tarjeta
recibe un product.template y el original buscaba el precio en product.product.
    """,
    "author": "PRIMATE, HSxTECH",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "19.0.2.0.0",
    "depends": [
        "point_of_sale",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "product_price_on_pos/static/src/**/*",
        ],
    },
    "license": "LGPL-3",
}
