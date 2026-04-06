# -*- coding: utf-8 -*-
{
    "name": "POS Fiserv — campos ITD en pagos (sin OCA)",
    "summary": "Campos pos.payment / account.payment para Fiserv cuando no está instalado odoo_pos_oca.",
    "description": """
Instale este módulo **solo** si usa odoo_pos_fiserv **sin** odoo_pos_oca.

Si tiene odoo_pos_oca instalado, los mismos campos ya los define ese módulo:
no instale este puente (evitaría duplicar campos en el registro).

Incluye: invoice_number, transacción, cuotas, sesión POS y vistas de formulario.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "odoo_pos_fiserv",
        "point_of_sale",
        "payment",
        "account",
        "account_payment",
    ],
    "data": [
        "views/pos_payment_views.xml",
        "views/account_payment_views.xml",
    ],
    "license": "LGPL-3",
}
