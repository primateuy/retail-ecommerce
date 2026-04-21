# -*- coding: utf-8 -*-
{
    "name": "OCA POSLink - Integración contable (account.payment)",
    "summary": "Cobro / devolución en terminal OCA (POSLink) desde el formulario de pago contable.",
    "description": """
Permite usar OCA POSLink desde ``account.payment``:
    - Botón «Crear transacción» cuando el diario usa un método integrado OCA.
    - Selección de terminal (PosID) cuando el proveedor es multi-terminal.
    - Fallback automático a ``processFinancialPurchaseRefund`` cuando la anulación
      falla porque el ticket no está en el lote actual del POS.
    - Acción custom «Registrar pago» en factura y grilla que reemplaza al wizard
      estándar ``account.payment.register`` y abre el form de pago directamente.

**No depende de** ``odoo_pos_oca`` (que es solo TPV): cliente puede tener el
backend OCA sin instalar el TPV OCA. Ambos módulos dependen de
``odoo_pos_oca_core``, que aporta la infraestructura compartida (provider,
transacción, terminal, helpers HTTP, worker).

Independiente de ``odoo_pos_fiserv_*``: cliente puede tener solo OCA, solo
Fiserv, o ambos. Comparten API POSLink pero cada stack es autónomo.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.1.0.8",
    "depends": [
        "odoo_pos_oca_core",
        "odoo_pos_oca_multiple",
        "account_accountant",
        # l10n_uy_einvoice_uruware añade los botones "Facturar" / "Obtener PDF"
        # al form de account.payment; los ocultamos cuando se usa terminal OCA.
        "l10n_uy_einvoice_uruware",
    ],
    "data": [
        "views/account_payment_views.xml",
        "views/account_move_views.xml",
        "wizard/account_payment_register_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_pos_oca_backend/static/src/services/oca_account_payment_bus_service.js",
            "odoo_pos_oca_backend/static/src/services/oca_account_payment_refresh_service.js",
        ],
    },
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
