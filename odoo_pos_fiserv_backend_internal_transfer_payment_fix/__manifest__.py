# -*- coding: utf-8 -*-
{
    "name": "Fiserv ITD - Puente con internal_transfer_payment_fix",
    "summary": "Aplica los xpaths Fiserv al form primary de internal_transfer_payment_fix.",
    "description": """
``internal_transfer_payment_fix`` (LocalizacionUy) define una vista
**primary** del form de account.payment. La primary hereda el arch del form
base con sus extensions ya aplicadas (incluyendo el backend Fiserv), pero
sobreescribe el ``invisible`` de los botones action_post / action_cancel /
action_draft con su propia lógica de transferencias internas, perdiendo así
las condiciones Fiserv.

Este módulo glue se ``auto_install`` cuando ambos módulos coexisten, y
re-aplica únicamente esos tres ``invisible`` combinando la lógica Fiserv
con la de internal_transfer (``counter_part_internal_transfer``,
``button_invisible``). NO duplica los elementos nuevos (botón Crear
Transacción, grupos, banners): esos vienen del backend a través del arch
heredado.

No se necesita en clientes sin LocalizacionUy.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Accounting/Payment",
    "version": "17.0.1.0.2",
    "depends": [
        "odoo_pos_fiserv_backend",
        "internal_transfer_payment_fix",
    ],
    "data": [
        "views/account_payment_views.xml",
    ],
    "auto_install": True,
    "license": "LGPL-3",
}
