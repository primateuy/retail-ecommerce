{
    "name": "POS Forum - Customer UI",
    "summary": "Customer create/edit UI and phone validation in POS",
    "description": """
        Personaliza la pantalla de alta de clientes en POS y valida telefono
        usando configuracion por pais. Agrega consultas de RUT cuando aplica.
    """,
    "author": "PRIMATE",
    "website": "https://www.primateuy.com",
    "category": "Point of Sale",
    "version": "17.0.1.3.0",
    "depends": [
        "point_of_sale",
        "l10n_uy_einvoice_base",
        "l10n_latam_base",
    ],
    "data": [
        "views/pos_config_views.xml",
        "views/res_country_views.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_customer_ui/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
