# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_pos_config(self):
        """
        Extiende la carga de pos.config para incluir el límite de días de devolución.

        Returns:
            dict: Parámetros de carga extendidos para pos.config.
        """
        # Obtener los parámetros base del POS
        result = super()._loader_params_pos_config()
        # Validar estructura antes de modificar la lista de campos
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
            and len(result["search_params"]["fields"]) > 0
        ):
            # Agregar el campo si aún no está presente
            if "refund_days_limit" not in result["search_params"]["fields"]:
                result["search_params"]["fields"].append("refund_days_limit")
        # Retornar los parámetros extendidos
        return result
