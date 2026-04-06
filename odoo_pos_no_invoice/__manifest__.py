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
    'depends': ['base', 'base_setup', 'point_of_sale', 'custom_receipts_for_pos', 'odoo_pos_oca'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/pos_config_views.xml',
        'data/pos_receipt_cfe_data.xml',
    ],
    'assets': {
        # Orden explícito: receipt_cfe_data.js debe ir al final para que el patch de
        # OrderReceipt (CFE + voucher OCA) sobrescriba al de custom_receipts_for_pos.
        'point_of_sale._assets_pos': [
            'odoo_pos_no_invoice/static/src/overrides/xml/ticket_screen_buttons.xml',
            'odoo_pos_no_invoice/static/src/overrides/components/payment_screen/payment_screen.js',
            'odoo_pos_no_invoice/static/src/overrides/components/receipt_screen/receipt_screen.js',
            'odoo_pos_no_invoice/static/src/overrides/printer/pos_printer_service.js',
            'odoo_pos_no_invoice/static/src/overrides/components/ticket_screen/reprint_receipt_button.js',
            'odoo_pos_no_invoice/static/src/overrides/components/ticket_screen/reprint_receipt_screen.js',
            'odoo_pos_no_invoice/static/src/js/receipt_cfe_data.js',
        ],
    },
    'license': 'LGPL-3',
}
