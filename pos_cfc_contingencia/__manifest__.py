# -*- coding: utf-8 -*-
{
    'name': 'POS — PDV de Contingencia CFC (Uruguay)',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': "Punto de venta dedicado para emisión de Comprobantes Fiscales "
               "de Contingencia (CFC). Banner + validación de folio en la "
               "pantalla de pago.",
    'description': """
Extiende el POS de Odoo para operar como PDV de Contingencia CFC. El cajero
ingresa el número de folio del talonario físico en el campo de referencia
de pago (provisto por pos_reference_for_payment) y este módulo:

  * Muestra un banner permanente con datos del CAE activo y vencimiento.
  * Valida el folio en frontend (vacío, entero, vencimiento, rango).
  * Propaga el folio a account.move.payment_reference para que la
    validación final del backend (l10n_uy_cfc_efac) opere correctamente.
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
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_cfc_contingencia/static/src/js/PaymentScreen.js',
            'pos_cfc_contingencia/static/src/xml/PaymentScreen.xml',
            'pos_cfc_contingencia/static/src/css/cfc_banner.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
