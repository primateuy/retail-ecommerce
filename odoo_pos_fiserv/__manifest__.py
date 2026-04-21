# -*- coding: utf-8 -*-
{
    "name": "POS Integración Fiserv ITD (meta)",
    "summary": "Meta-módulo: instala core + POS + backend de la integración Fiserv ITD.",
    "description": """
Este módulo fue dividido en la versión 17.0.2.0.0 en tres módulos:
    - odoo_pos_fiserv_core: infraestructura común (proveedor, terminal, transacción, voucher)
    - odoo_pos_fiserv_pos: integración con el punto de venta
    - odoo_pos_fiserv_backend: integración con account.payment

Este módulo se conserva como meta para que los clientes con el paquete antiguo
actualicen con ``./update.sh -u odoo_pos_fiserv`` y reciban los tres hijos. Un
script de migración renombra los xml_ids ``odoo_pos_fiserv.*`` al módulo que
corresponde, preservando credenciales y datos ya cargados.

Para instalaciones nuevas, conviene instalar directamente solo los módulos
requeridos (solo backend, solo POS o ambos) en lugar de este meta.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "17.0.2.0.0",
    "depends": [
        "odoo_pos_fiserv_core",
        "odoo_pos_fiserv_pos",
        "odoo_pos_fiserv_backend",
    ],
    "data": [],
    "license": "LGPL-3",
    "auto_install": False,
}
