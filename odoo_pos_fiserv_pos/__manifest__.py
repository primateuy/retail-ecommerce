# -*- coding: utf-8 -*-
{
    "name": "Fiserv ITD - Integración POS",
    "summary": "Terminal Fiserv ITD en el Punto de Venta (flujo POS).",
    "description": """
Integra el terminal Fiserv ITD con el punto de venta: processFinancialPurchase,
Query, cancel, void por ticket, reverse; multi-POS; ticket de cambio; voucher PDF
y pos.config.

La infraestructura Fiserv compartida (proveedor, terminal, transacción, reporte
voucher, helpers HTTP) vive en 'odoo_pos_fiserv_core'. Para el cobro contable
sin POS instalar 'odoo_pos_fiserv_backend'.

Coexistencia con odoo_pos_oca: si OCA está instalado, los campos extra en
pos.payment los aporta OCA; sin OCA, instale 'odoo_pos_fiserv_pos_payment'.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.2.0.2",
    "depends": [
        "odoo_pos_fiserv_core",
        "point_of_sale",
    ],
    "data": [
        "data/fiserv_pos_installation_data.xml",
        "data/fiserv_change_ticket_report_data.xml",
        "views/pos_payment_method_views.xml",
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "odoo_pos_fiserv_pos/static/src/app/**/*",
            "odoo_pos_fiserv_pos/static/src/overrides/**/*",
        ],
    },
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
