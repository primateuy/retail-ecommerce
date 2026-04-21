# -*- coding: utf-8 -*-
{
    "name": "Fiserv ITD - Integración contable (account.payment)",
    "summary": "Cobro / devolución en terminal Fiserv ITD desde el formulario de pago contable.",
    "description": """
Permite usar Fiserv ITD desde ``account.payment``:
    - Checkbox «Cobrar en terminal Fiserv (ITD)» en pagos borrador.
    - Selección de terminal (PosID) cuando el proveedor es multi-terminal.
    - Devolución por ticket contra una transacción Fiserv original.
    - Wizard de registro de pago (desde facturas) con la misma opción.

No depende de 'point_of_sale'. La infraestructura Fiserv (proveedor,
transacción, terminal, reporte voucher) vive en 'odoo_pos_fiserv_core'.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.2.0.5",
    "depends": [
        "odoo_pos_fiserv_core",
        "account_accountant",
        # l10n_uy_einvoice_uruware añade los botones "Facturar" / "Obtener PDF"
        # al form de account.payment; los ocultamos cuando se usa terminal Fiserv.
        "l10n_uy_einvoice_uruware",
    ],
    "data": [
        "views/account_payment_views.xml",
        "views/account_move_views.xml",
        "wizard/account_payment_register_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_pos_fiserv_backend/static/src/services/account_payment_fiserv_bus_service.js",
            "odoo_pos_fiserv_backend/static/src/services/account_payment_fiserv_refresh_service.js",
        ],
    },
    "pre_init_hook": "pre_init_hook",
    "license": "LGPL-3",
}
