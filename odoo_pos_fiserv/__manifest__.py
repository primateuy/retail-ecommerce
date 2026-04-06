# -*- coding: utf-8 -*-
{
    "name": "POS Integración Fiserv ITD",
    "summary": "Terminal de pago Fiserv ITD en Punto de Venta.",
    "description": """
Integración POS con Fiserv ITD: mismos endpoints y flujo ITD
(processFinancialPurchase, Query, cancel, void por ticket, reverse), multi-POS,
ticket de cambio, voucher PDF y pos.config.

Coexistencia con odoo_pos_oca: si OCA está instalado, los campos en pos.payment /
account.payment los define odoo_pos_oca; basta con instalar este módulo Fiserv.

Pago contable: opción «Cobrar en terminal Fiserv (ITD)», PosID si aplica; al confirmar
processFinancialPurchase / void por ticket directo a ITD (POST + hilo), sin sesión de caja ni bus.
Devolución: transacción Fiserv original con ticket; importe al 100%.

Sin OCA: instale «odoo_pos_fiserv_pos_payment» (depende de este módulo) para los mismos
campos y vistas; no lo instale si ya tiene odoo_pos_oca (campos duplicados).
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.6.6",
    "depends": [
        "base",
        "bus",
        "point_of_sale",
        "payment",
        "account",
        "account_payment",
        "account_accountant",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/fiserv_installation_data.xml",
        "data/fiserv_change_ticket_report_data.xml",
        "data/fiserv_voucher_report_data.xml",
        "views/payment_provider_views.xml",
        "views/pos_payment_method_views.xml",
        "views/payment_transaction_views.xml",
        "views/account_payment_views.xml",
        "views/pos_config_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_pos_fiserv/static/src/services/account_payment_fiserv_refresh_service.js",
        ],
        "point_of_sale._assets_pos": [
            "odoo_pos_fiserv/static/src/app/**/*",
            "odoo_pos_fiserv/static/src/overrides/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
