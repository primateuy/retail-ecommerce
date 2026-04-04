# -*- coding: utf-8 -*-
{
    "name": "POS Integración Fiserv ITD",
    "summary": "Terminal de pago Fiserv ITD en Punto de Venta.",
    "description": """
Integración POS con Fiserv ITD: mismos endpoints y flujo que odoo_pos_oca
(processFinancialPurchase, Query, cancel, void por ticket, reverse), multi-POS
como odoo_pos_oca_multiple (proveedor + terminales), ticket de cambio y botones
en recibo, voucher PDF, vistas pos.payment / account.payment / pos.config.

No instalar junto con odoo_pos_oca: ambos definen los mismos campos en pos.payment
(payment_transaction_id, etc.) y fallará el registro de modelos.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "base",
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
        "views/pos_payment_views.xml",
        "views/account_payment_views.xml",
        "views/payment_transaction_views.xml",
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "odoo_pos_fiserv/static/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
