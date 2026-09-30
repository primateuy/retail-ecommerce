# -*- coding: utf-8 -*-
{
    "name": "Fiserv ITD - Core",
    "summary": "Infraestructura compartida Fiserv ITD (proveedor, transacción, terminal, reporte voucher).",
    "description": """
Módulo base para la integración Fiserv ITD. Provee:
    - payment.provider con código 'fiserv' y credenciales ITD. La
      instalación lo crea deshabilitado y sin credenciales.
    - fiserv.pos.terminal (PosID del pinpad, multi-terminal).
    - payment.transaction extendida con campos de tarjeta/ticket/respuesta y
      el bucle de consultas ITD (un fallo de transporte deja la transacción
      pendiente, nunca en error).
    - Reporte de voucher PDF.

No arrastra dependencia de 'point_of_sale'. Para el flujo contable instalar
'odoo_pos_fiserv_backend'.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "19.0.1.0.0",
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
        # Después del payment.method: el orden del manifest es el orden de carga.
        "data/payment_provider_data.xml",
        "data/fiserv_voucher_report_data.xml",
        "views/fiserv_pos_terminal_views.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
    ],
    "license": "LGPL-3",
}
