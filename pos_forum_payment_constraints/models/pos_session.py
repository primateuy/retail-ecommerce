# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_pos_payment_method(self):
        """
        Extiende la carga de métodos de pago para incluir flags de control.

        Returns:
            dict: Parámetros de carga extendidos para pos.payment.method.
        """
        # Obtener los parámetros base del POS
        result = super()._loader_params_pos_payment_method()
        # Validar estructura antes de modificar la lista de campos
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
        ):
            # Agregar los campos de control si no están presentes
            extra_fields = [
                "readonly_opening_cash",
                "readonly_closing_non_cash",
                "limit_closing_cash_to_balance",
            ]
            for field_name in extra_fields:
                if field_name not in result["search_params"]["fields"]:
                    result["search_params"]["fields"].append(field_name)
        # Retornar los parámetros extendidos
        return result
