# -*- coding: utf-8 -*-
{
    'name': 'POS — PDV de Contingencia CFC (Uruguay)',
    'version': '17.0.1.2.0',
    'category': 'Point of Sale',
    'summary': "Punto de venta dedicado para emisión de Comprobantes Fiscales "
               "de Contingencia (CFC). Banner + validación de folio en la "
               "pantalla de pago.",
    'description': """
Extiende el POS de Odoo para operar como PDV de Contingencia CFC. Un PDV es de
contingencia cuando su diario de FACTURAS lo es. Al validar el pago el POS pide
el número de folio del talonario físico y este módulo:

  * Muestra un banner permanente con datos del CAE activo y vencimiento.
  * Valida el folio en frontend (vacío, entero, vencimiento, rango).
  * Propaga el folio a account.move.payment_reference para que la
    validación final del backend (l10n_uy_cfc_efac) opere correctamente.
  * Si una orden llega sin folio válido, la guarda sin facturar (con el motivo
    en la ficha de la orden) en vez de trabar la sincronización; el folio se carga en la
    orden y se factura desde el backend.
  * Permite configurar envío a UCFE online vs batch por pos.config.
    """,
    'author': 'Primate UY',
    'website': 'https://www.primate.uy',
    'license': 'OPL-1',
    'depends': [
        'point_of_sale',
        'l10n_uy_cfc_efac',
        'pos_reference_for_payment',
    ],
    'data': [
        'views/pos_config_views.xml',
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_cfc_contingencia/static/src/js/Order.js',
            'pos_cfc_contingencia/static/src/js/PaymentScreen.js',
            'pos_cfc_contingencia/static/src/xml/PaymentScreen.xml',
            'pos_cfc_contingencia/static/src/css/cfc_banner.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
