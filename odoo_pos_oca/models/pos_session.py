# -*- coding: utf-8 -*-
"""
Modelo para extender pos.session con funcionalidades específicas de OCA

Este módulo extiende la sesión POS para incluir campos específicos
de OCA en los parámetros de carga de métodos de pago.
"""

from odoo import models


class PosSession(models.Model):
    """
    Extensión del modelo pos.session para integración con OCA
    
    Agrega campos específicos de OCA a los parámetros de carga
    de métodos de pago en la sesión POS, permitiendo que el frontend
    tenga acceso a la configuración necesaria para las transacciones OCA.
    """
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        """
        Extiende los parámetros de carga de métodos de pago para incluir campos OCA
        
        Returns:
            dict: Parámetros de carga extendidos con campos específicos de OCA
        """
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].append('codigo_sistema')
        result['search_params']['fields'].append('codigo_terminal')
        result['search_params']['fields'].append('client_app_id')
        result['search_params']['fields'].append('codigo_sucursal')
        return result
