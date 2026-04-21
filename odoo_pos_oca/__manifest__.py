{
    'name': "POS INTEGRACION OCA (TPV)",
    'summary': """Integración OCA POSLink en el Punto de Venta.""",
    'description': """
Módulo POS para OCA POSLink. Flujo de cobro, anulación, reverso y ticket de
cambio desde el TPV. La infraestructura compartida (provider, payment.transaction,
oca.pos.terminal, helpers HTTP, worker) vive en 'odoo_pos_oca_core'.

Para el flujo contable (account.payment) instalar 'odoo_pos_oca_backend'.
    """,
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Point of Sale',
    'version': '17.0.2.1.2',
    'depends': [
        'odoo_pos_oca_core',
        'odoo_pos_oca_multiple',
        'point_of_sale',
    ],
    'data': [
        'data/oca_installation_data.xml',
        'data/change_ticket_report_data.xml',
        'views/pos_payment_method_views.xml',
        'views/pos_payment_method_multiple_views.xml',
        'views/pos_payment_views.xml',
        'views/account_payment_views.xml',
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'odoo_pos_oca/static/**/*',
        ],
    },
    'pre_init_hook': 'pre_init_hook',
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
}
