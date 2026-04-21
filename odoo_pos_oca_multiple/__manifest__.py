{
    'name': "POS INTEGRACION OCA MULTIPLE",
    'summary': """Configuración multi-POS (is_multiple + tab + multiple.pos.config) para OCA POSLink.""",
    'description': """
Provee al proveedor OCA POSLink el checkbox «Tiene multiples POS» y el tab
«Configuración Multiple POS» para registrar los PosID disponibles. Define
el modelo ``multiple.pos.config``.

No depende del TPV: tanto ``odoo_pos_oca`` (TPV) como ``odoo_pos_oca_backend``
(contable) dependen de este módulo para reutilizar la misma config.
    """,
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Localization',
    'version': '17.0.2.0.0',
    'depends': ['odoo_pos_oca_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_provider_views.xml',
    ],
    'license': 'LGPL-3',
}
