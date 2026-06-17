# -*- coding: utf-8 -*-
{
    "name": "Fiserv ITD - Core",
    "summary": "Infraestructura compartida Fiserv ITD (proveedor, transacción, terminal, reporte voucher).",
    "description": """
Módulo base para la integración Fiserv ITD. Provee:
    - payment.provider con código 'fiserv' y credenciales ITD.
    - fiserv.pos.terminal (PosID del pinpad, multi-terminal).
    - payment.transaction extendida con campos de tarjeta/ticket/respuesta.
    - Helpers HTTP ITD y worker de hilo para cobros contables.
    - Reporte de voucher PDF.

No arrastra dependencia de 'point_of_sale'. Para el flujo POS instalar
'odoo_pos_fiserv_pos'. Para el flujo contable instalar 'odoo_pos_fiserv_backend'.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.2.0.19",
    "depends": [
        "base",
        "bus",
        "account",
        "payment",
        "account_payment",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/fiserv_installation_data.xml",
        "data/fiserv_card_brands.xml",
        "data/fiserv_voucher_report_data.xml",
        "views/fiserv_pos_terminal_views.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
    ],
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
