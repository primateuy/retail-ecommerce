# -*- coding: utf-8 -*-
{
    "name": "Getnet TransAct - Flags unificados POS integrado",
    "summary": "Suma las condiciones Getnet a los flags pos_integrated_* de odoo_pos_fiserv_backend.",
    "description": """
Puente auto-instalable cuando conviven odoo_pos_getnet_backend y
odoo_pos_fiserv_backend: extiende _compute_pos_integrated_flags para que
los botones Confirmar/Cancelar/Borrador respeten también el estado de las
transacciones Getnet, sin duplicar flags (el último inherit de vista
sobreescribe los position=attributes, por eso los flags son compartidos).
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.1.0.0",
    "depends": [
        "odoo_pos_getnet_backend",
        "odoo_pos_fiserv_backend",
    ],
    "auto_install": True,
    "license": "LGPL-3",
}
