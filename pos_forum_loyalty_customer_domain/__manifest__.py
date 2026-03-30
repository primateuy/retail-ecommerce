# -*- coding: utf-8 -*-
{
    "name": "POS Forum - Customer domain en lealtad",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Aplica dominios de cliente de reglas de lealtad en el POS con campos "
    "cargados en sesión y validación para programas con Punto de venta.",
    "description": """
        Extiende el módulo de dominio de cliente en lealtad para el TPV:
        - Carga customer_domain en las reglas y category_id (y campos base) en partners.
        - Filtra recompensas reclamables y el cómputo de puntos según el dominio.
        - Tras cambiar de cliente, si existe ``_applyCustomRewardsOnly`` (p. ej. módulo
          de lista promo en TPV), lo vuelve a ejecutar para reaplicar lista/precio al
          volver a un partner elegible.
        - Restringe el dominio a campos presentes en el cache del POS si el programa
          tiene «Punto de venta» activo.
    """,
    "author": "PRIMATE",
    "website": "https://www.primateuy.com",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "pos_loyalty",
        "loyality_customer_domain",
    ],
    "data": [
        "views/loyalty_rule_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_loyalty_customer_domain/static/src/js/pos_loyalty_customer_domain.js",
        ],
    },
    "installable": True,
    "application": False,
}
