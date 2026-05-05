{
    'name': 'POS - Asegurar Lista de Precio en Reembolso',
    'version': '17.0.1.1.0',
    'category': 'Point of Sale',
    'summary': 'Al crear un reembolso en POS, la nueva orden hereda la lista de precio de la orden original y bloquea su cambio salvo que la heredada sea la default del POS.',
    'author': 'PRIMATE',
    'website': 'https://www.primate.uy',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'asegurar_lista_precio_reembolso/static/src/overrides/ticket_screen_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
