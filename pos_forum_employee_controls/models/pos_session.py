# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_hr_employee(self):
        """
        Extiende la carga de empleados para incluir permisos del POS
        y el numero de documento para busquedas en frontend.

        Returns:
            dict: Parametros de carga extendidos para hr.employee.
        """
        # Obtener parametros base del POS
        result = super()._loader_params_hr_employee()

        # Validar estructura antes de modificar
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
        ):
            # Agregar campos de permisos y documento si no existen
            extra_fields = [
                "identification_id",
                "pos_allow_refund_button",
                "pos_allow_pricelist_button",
                "pos_allow_customer_note_button",
                "pos_allow_discount_button",
                "pos_allow_salesperson_button",
                "pos_allow_z_report_button",
                "pos_allow_ewallet_button",
                "pos_allow_promo_code_button",
                "pos_allow_reward_button",
                "pos_allow_reset_programs_button",
                "pos_allow_quotation_button",
                "pos_allow_numpad_discount",
                "pos_allow_numpad_price",
            ]
            for field_name in extra_fields:
                if field_name not in result["search_params"]["fields"]:
                    result["search_params"]["fields"].append(field_name)

        # Retornar parametros extendidos
        return result
