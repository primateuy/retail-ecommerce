# -*- coding: utf-8 -*-
{
    "name": "OCA POSLink - Core",
    "summary": "Infraestructura compartida OCA POSLink (proveedor, transacción, helpers).",
    "description": """
Módulo base para la integración OCA POSLink. Provee:
    - payment.provider con código 'oca' + campos base de conexión
      (url_webservice, codigo_sistema, client_app_id, codigo_sucursal, branch).
    - payment.transaction extendida con campos de tarjeta/ticket/respuesta OCA
      y métodos del bucle Query.
    - Helpers HTTP POSLink y worker de hilo para cobros contables.

La configuración multi-POS (is_multiple, multiple_pos_ids, multiple.pos.config
y tab "Configuración Multiple POS") vive en ``odoo_pos_oca_multiple`` y se
arrastra automáticamente desde ``odoo_pos_oca`` y ``odoo_pos_oca_backend``.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.2.1.4",
    "depends": [
        "base",
        "bus",
        "account",
        "payment",
        "account_payment",
        "point_of_sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/oca_installation_data.xml",
        "views/payment_provider_views.xml",
        "views/payment_transaction_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "odoo_pos_oca_core/static/src/overrides/xml/payment_lines.xml",
        ],
    },
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
