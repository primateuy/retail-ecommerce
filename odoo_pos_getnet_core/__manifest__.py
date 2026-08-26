# -*- coding: utf-8 -*-
{
    "name": "Getnet TransAct - Core",
    "summary": "Infraestructura compartida Getnet/TransAct v4 (proveedor, transacción, terminal, motor de polling).",
    "description": """
Módulo base para la integración con Getnet a través de TransAct v4 (New Age
Data) en modo WebServices (SOAP contra el Concentrador de Facturas). Provee:
    - payment.provider con código 'getnet' y credenciales TransAct
      (EmpHash / EmpCod / URL del concentrador).
    - getnet.pos.terminal (TermCod del POS, multi-terminal) con lock
      cross-flujo: el posteo TransAct es serial por terminal, por lo que
      backend y TPV deben excluirse mutuamente sobre el mismo pinpad.
    - payment.transaction extendida con token/ticket/lote/voucher y el
      motor de polling PostearTransaccion -> ConsultarTransaccion.
    - Cliente SOAP propio (requests + lxml, sin dependencias nuevas).

No arrastra dependencia de 'point_of_sale'. Para el flujo POS instalar
'odoo_pos_getnet_pos'. Para el flujo contable instalar
'odoo_pos_getnet_backend'.

Referencias: "Manual de Integración TransAct v4.00.22" (TRA.GEN.MAN v1.3)
y "Integración WebServices TransAct v4.0.09" (WS v02).
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.1.0.0",
    "depends": [
        "base",
        "bus",
        "account",
        "payment",
        "account_payment",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/getnet_cron.xml",
        "data/getnet_payment_method.xml",
        "views/getnet_pos_terminal_views.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
    ],
    "license": "LGPL-3",
}
