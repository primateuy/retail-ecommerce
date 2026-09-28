# -*- coding: utf-8 -*-
{
    "name": "Getnet TransAct - POS Backend",
    "summary": "Terminal Getnet/TransAct para los medios integrados del POS Backend.",
    "description": """
Implementa el contrato de terminales de `pos_backend` (Sprint 12,
doc/contrato-terminales.md) contra Getnet/TransAct v4.

Las cinco operaciones obligatorias, la 6 deliberadamente NO —Getnet no sabe
si el adquirente liquidó, y el «no sé» del contrato es la respuesta correcta,
que además elige el camino barato— y la 7 (cierre de lote) sobre el
`getnet.lote.cierre` que ya modela el núcleo.

La regla que gobierna todo el módulo: **NUNCA se commitea la transacción del
POS que nos llama.** Los hooks corren dentro de la transacción de quien pide
el cobro, así que el claim de la terminal y el posteo a TransAct van en un
cursor propio y aislado. Ninguna llamada espera al pinpad más que unos
segundos: la pantalla consulta sola con llamadas cortas (`terminal_query`)
hasta el tope del pinpad, y lo que queda en «no sé» lo sigue el cron de
recuperación, que además pone al día la línea del POS.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "19.0.1.0.0",
    "depends": [
        "odoo_pos_getnet_core",
        "pos_backend",
    ],
    "data": [
        "data/getnet_pos_backend_cron.xml",
        "views/pos_backend_box_payment_method_views.xml",
    ],
    "license": "LGPL-3",
}
