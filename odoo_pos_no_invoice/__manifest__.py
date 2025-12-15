{
    'name': "ODOO POS NO INVOICE",
    'summary': """No descargar la factura en el POS y recibo con información CFE""",
    'description': """
        Módulo que permite:
        1. No descargar la factura en el POS
        2. Agregar un diseño de recibo personalizado con información del CFE
           (Comprobante Fiscal Electrónico) después de la facturación.
        
        Requiere el módulo custom_receipts_for_pos para funcionar correctamente.
    """,
    'category': 'Localization',
    'version': '17.0.0.1',
    'depends': ['base', 'point_of_sale', 'custom_receipts_for_pos'],
    'data': [
        'views/pos_config_views.xml',
        'data/pos_receipt_cfe_data.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'odoo_pos_no_invoice/static/**/*',
        ],
    },
    'license': 'LGPL-3',
}
