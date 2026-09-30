# -*- coding: utf-8 -*-
{
    "name": "Getnet TransAct - Fiserv ITD: convivencia en el pago contable",
    "summary": "Puente auto-instalable: Getnet y Fiserv en la misma base sin pisarse en el form del pago.",
    "description": """
Se instala solo cuando conviven odoo_pos_getnet_backend y
odoo_pos_fiserv_backend. Cada backend suma sus propios bloqueos a los botones
del pago (Confirmar / Cancelar / Borrador / Rechazar) y este puente hace que
los términos de uno NO bloqueen un pago del otro: un pago tiene una sola línea
de método y es esa la que manda. Además limpia el check «cobrar en terminal»
del otro adquirente antes de cobrar, y hace que «Pagar» en la factura cargue
las facturas origen para los dos.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "19.0.1.0.0",
    "depends": [
        "odoo_pos_getnet_backend",
        "odoo_pos_fiserv_backend",
    ],
    "auto_install": True,
    "license": "LGPL-3",
}
