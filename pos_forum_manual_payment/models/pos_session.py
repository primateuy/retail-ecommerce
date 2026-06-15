# -*- coding: utf-8 -*-
"""
Extensión de carga de datos POS para pagos manuales.

Este modelo asegura que los campos de configuración manual de los métodos
de pago estén disponibles en el frontend del POS.
"""

from odoo import models


class PosSession(models.Model):
    """
    Extiende la sesión POS para exponer campos manuales al frontend.

    Los campos agregados se usan en JS para decidir cuándo abrir el popup
    de captura de datos de transacción manual.
    """

    _inherit = "pos.session"

    def _loader_params_pos_payment_method(self):
        """
        Agrega campos de método de pago requeridos por el flujo manual.

        Se reutiliza la carga estándar y se incorporan los campos necesarios
        para que el frontend pueda evaluar la configuración de cada método.
        """
        result = super()._loader_params_pos_payment_method()
        fields_to_add = [
            "manual_transaction_enabled",
            "manual_provider_id",
            "manual_create_checks",
            "manual_payment_popup_config",
            "no_print_voucher",
        ]
        for field_name in fields_to_add:
            if field_name not in result["search_params"]["fields"]:
                result["search_params"]["fields"].append(field_name)
        return result

