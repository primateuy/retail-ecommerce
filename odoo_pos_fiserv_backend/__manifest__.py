# -*- coding: utf-8 -*-
{
    "name": "Fiserv ITD - Integración contable (account.payment)",
    "summary": "Cobro / devolución en terminal Fiserv ITD desde el formulario de pago contable.",
    "description": """
Permite usar Fiserv ITD desde ``account.payment``:
    - «Crear transacción»: envía el cobro al pinpad; al aprobar, el pago
      queda en borrador y el usuario Confirma (nunca auto-post).
    - Selección de terminal (PosID) cuando el proveedor es multi-terminal.
    - Devolución por ticket contra una transacción Fiserv original (anulación
      o refund según el lote).
    - «Reconsultar en ITD» para operaciones que quedaron sin resultado.
    - «Pagar» en la factura abre el pago con la factura precargada (sólo con
      un proveedor Fiserv habilitado).

No depende de 'point_of_sale'. La infraestructura Fiserv (proveedor,
transacción, terminal, reporte voucher) vive en 'odoo_pos_fiserv_core'.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "19.0.1.0.0",
    "depends": [
        "odoo_pos_fiserv_core",
        # l10n_uy_einvoice_uruware añade los botones "Facturar" / "Obtener PDF"
        # al form de account.payment; se ocultan en los pagos Fiserv.
        "l10n_uy_einvoice_uruware",
    ],
    "data": [
        "views/account_payment_views.xml",
        "views/account_move_views.xml",
        "wizard/account_payment_register_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_pos_fiserv_backend/static/src/services/account_payment_fiserv_refresh_service.js",
        ],
    },
    "license": "LGPL-3",
}
