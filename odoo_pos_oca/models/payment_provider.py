# -*- coding: utf-8 -*-
"""
Modelo para extender payment.provider con soporte para OCA

Este módulo agrega el proveedor de pago OCA a la lista de proveedores
disponibles en Odoo, permitiendo su configuración y uso en el sistema.
"""

import logging
from odoo import _, fields, models
_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    """
    Extensión del modelo payment.provider para incluir OCA
    
    Agrega OCA como una opción de proveedor de pago en el sistema,
    permitiendo su configuración y gestión a través de la interfaz
    estándar de Odoo.
    """
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('oca', "OCA")], ondelete={'oca': 'set default'})
