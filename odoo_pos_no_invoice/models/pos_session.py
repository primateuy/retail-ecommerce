# -*- coding: utf-8 -*-
"""
Modelo para extender pos.session y asegurar que el campo download_invoice
esté disponible en el frontend
"""

from odoo import models


class PosSession(models.Model):
    """
    Extensión del modelo pos.session para asegurar que el campo download_invoice
    de pos.config esté disponible en el frontend
    """
    _inherit = 'pos.session'

    def _loader_params_pos_config(self):
        """
        Extiende los parámetros de carga de pos.config para incluir el campo download_invoice
        
        Este método asegura que el campo download_invoice esté disponible en el frontend
        para que el JavaScript pueda verificar la configuración antes de aplicar
        el comportamiento personalizado.
        
        IMPORTANTE: Solo agrega download_invoice a la lista de campos si el método padre
        ya está especificando campos específicos. Si el método padre no especifica campos,
        Odoo carga todos los campos por defecto (incluyendo download_invoice), por lo que
        no necesitamos hacer nada.
        
        Returns:
            dict: Parámetros de carga extendidos con el campo download_invoice si aplica
        """
        # Llamar al método padre para obtener todos los parámetros estándar
        result = super()._loader_params_pos_config()
        
        # Solo modificar si el resultado tiene la estructura esperada y ya especifica campos
        # Si no especifica campos, Odoo carga todos los campos por defecto
        if (result and 
            isinstance(result, dict) and 
            'search_params' in result and 
            'fields' in result['search_params'] and 
            isinstance(result['search_params']['fields'], list) and
            len(result['search_params']['fields']) > 0):
            # Solo agregar download_invoice si hay una lista de campos específicos
            # y download_invoice no está ya en la lista
            if 'download_invoice' not in result['search_params']['fields']:
                result['search_params']['fields'].append('download_invoice')
        
        return result

