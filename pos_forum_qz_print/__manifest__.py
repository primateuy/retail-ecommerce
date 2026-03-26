# -*- coding: utf-8 -*-
{
    "name": "POS Forum — Impresión QZ Tray",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Ticket de cambio y recibo POS vía QZ Tray (impresora local sin diálogo del navegador).",
    "description": """
Impresión directa con QZ Tray
=============================

* Opción por **configuración del POS**: activar QZ Tray e indicar el **nombre exacto**
  de la impresora tal como la lista el sistema operativo / QZ Tray.
* **Ticket de cambio** (odoo_pos_oca): si QZ está activo, se envía el HTML del
  reporte QWeb a la impresora vía QZ; si no, se mantiene el comportamiento del
  módulo base (descarga PDF con report.doAction).
* **Recibo del POS** (opcional): campo para imprimir también el recibo estándar
  por QZ en lugar del flujo habitual del navegador.

Requisitos
----------

* Instalar y ejecutar **QZ Tray** en cada PC de caja (`https://qz.io/`).
* Sustituir `digital-certificate.txt` por el certificado firmado según la
  documentación de QZ cuando pase a producción (el archivo incluido es plantilla).

Librerías JS en `static/src/lib/` proceden del conector QZ (referencia módulo
pos_qz_printer Kanak / QZ Tray).
    """,
    "author": "PRIMATE",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "odoo_pos_oca"],
    "data": [
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_qz_print/static/src/lib/rsvp-3.1.0.min.js",
            "pos_forum_qz_print/static/src/lib/sha-256.min.js",
            "pos_forum_qz_print/static/src/lib/qz-tray.js",
            "pos_forum_qz_print/static/src/js/qz_print_service.js",
            "pos_forum_qz_print/static/src/js/receipt_screen_qz.js",
        ],
    },
    "installable": True,
    "application": False,
}
