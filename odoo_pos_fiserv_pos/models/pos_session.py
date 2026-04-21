# -*- coding: utf-8 -*-
"""
Extiende pos.session para cargar en el POS los campos del terminal Fiserv ITD.
"""

from odoo import models


class PosSession(models.Model):
    """
    Incluye credenciales y referencias Fiserv en los datos del método de pago POS.
    """

    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        """
        Añade campos necesarios para PaymentFiserv en el frontend (OWL).

        Returns:
            dict: Parámetros de búsqueda extendidos.
        """
        result = super()._loader_params_pos_payment_method()
        fields_list = result['search_params']['fields']
        for fname in (
            'url_webservice',
            'codigo_sistema',
            'codigo_terminal',
            'client_app_id',
            'codigo_sucursal',
            'fiserv_branch',
            'fiserv_provider_id',
            'fiserv_terminal_id',
            'fiserv_provider_is_multiple',
        ):
            if fname not in fields_list:
                fields_list.append(fname)
        return result
