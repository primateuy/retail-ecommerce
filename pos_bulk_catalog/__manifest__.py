# -*- coding: utf-8 -*-
{
    "name": "POS Bulk Catalog Cache",
    "summary": "Caché por lotes y cron para cargar productos, clientes y tarifas en el POS sin bloquear el navegador.",
    "version": "17.0.1.0.8",
    "category": "Point of Sale",
    "author": "Forum Primate (basado en concepto pos_fast_loading)",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/pos_bulk_catalog_views.xml",
    ],
    "installable": True,
    "application": False,
}
