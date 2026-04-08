# -*- coding: utf-8 -*-
{
    "name": "Transferencia de transacciones de pago",
    "summary": (
        "Acción en listado de payment.transaction para agrupar por diario del "
        "proveedor y generar transferencias internas hacia un diario destino."
    ),
    "version": "17.0.1.1.3",
    "author": "PRIMATE",
    "website": "https://www.primate.uy",
    "category": "Accounting/Payment",
    "license": "LGPL-3",
    "depends": [
        "account_payment",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/payment_transaction_transfer_views.xml",
    ],
    "installable": True,
    "application": False,
}
