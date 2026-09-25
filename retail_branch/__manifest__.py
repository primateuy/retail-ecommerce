# -*- coding: utf-8 -*-
{
    'name': 'Sucursal — ancla de local',
    'version': '17.0.1.0.0',
    'author': 'PRIMATE',
    'website': 'https://primate.uy',
    'category': 'Inventory/Inventory',
    'license': 'LGPL-3',
    'summary': """Representa la sucursal con el almacén: quién trabaja en ella, qué PDV
        factura, y la sincronización de compañías que permite operar a través de la
        frontera de compañía.""",
    'description': """
        El ancla de sucursal, sin ninguna política de permisos encima.

        En una cadena con franquicias la sucursal es la única entidad que cruza la
        frontera de compañía: el local factura en el PDV de la franquicia pero mueve el
        inventario en un almacén de la casa central. Este módulo modela ese vínculo y se
        ocupa de la única consecuencia técnica que tiene: que las reglas multicompañía de
        stock y de punto de venta usan ('company_id', 'in', company_ids), sin jerarquía,
        así que el usuario necesita las dos compañías en company_ids para operar.

        No define grupos, ni restringe nada. El perfil de permisos que se apoya en esto
        vive en forum_branch_security, que depende de un módulo de pago; el ancla no, y
        por eso es reutilizable en cualquier cliente.
    """,
    'depends': [
        'stock',
        'point_of_sale',
    ],
    'data': [
        'views/stock_warehouse_views.xml',
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
}
