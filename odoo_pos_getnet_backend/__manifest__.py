# -*- coding: utf-8 -*-
{
    "name": "Getnet TransAct - Backend",
    "summary": "Cobro con terminal Getnet/TransAct desde pagos contables (account.payment).",
    "description": """
Flujo contable de la integración Getnet/TransAct v4:
    - Botón «Crear transacción Getnet» en account.payment: postea la
      factura al concentrador y un worker consulta hasta resolución.
    - Al aprobar, el pago queda en borrador y el usuario Confirma
      (nunca auto-post); draft/cancel bloqueados con transacción aprobada.
    - Devoluciones como pago saliente: operación DEV + TicketOriginal
      de la transacción original.
    - FacturaNro/Gravado/IVA/ConsumidorFinal desde el CFE de la factura
      origen (l10n_uy_einvoice_base).
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.1.0.0",
    "depends": [
        "odoo_pos_getnet_core",
        "l10n_uy_einvoice_base",
    ],
    "data": [
        "views/account_payment_views.xml",
        "wizard/account_payment_register_views.xml",
    ],
    "license": "LGPL-3",
}
