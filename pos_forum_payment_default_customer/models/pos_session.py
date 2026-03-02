# -*- coding: utf-8 -*-
from odoo import models
from odoo.osv.expression import OR


class PosSession(models.Model):
    """
    Extiende la sesión POS para cargar el cliente por defecto de pago en el config
    y asegurar que ese partner esté disponible en la UI (incluyéndolo en la carga de res.partner).
    """

    _inherit = "pos.session"

    def _loader_params_pos_config(self):
        """
        Incluye el ID del cliente por defecto al pago en los datos de config
        que recibe el frontend. Solo añade el campo si la lista de fields ya
        es no vacía; si está vacía, no se toca para que search_read devuelva
        todos los campos (p. ej. is_posbox) y no se produzca KeyError.
        """
        result = super()._loader_params_pos_config()
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
        ):
            fields = result["search_params"]["fields"]
            # No modificar si está vacía: en la base POS fields=[] significa "todos los campos"
            if fields and "payment_default_customer_id" not in fields:
                result["search_params"]["fields"].append("payment_default_customer_id")
        return result

    def _loader_params_res_partner(self):
        """
        Incluye en la carga de partners al cliente por defecto de pago del POS
        para que esté disponible en el frontend al aplicar al entrar a pagar.

        Returns:
            dict: Parámetros de carga extendidos para res.partner.
        """
        result = super()._loader_params_res_partner()
        if not result or not isinstance(result, dict) or "search_params" not in result:
            return result

        self.ensure_one()
        partner_id = self.config_id.payment_default_customer_id
        if not partner_id:
            return result

        domain = result.get("search_params", {}).get("domain", [])
        if not isinstance(domain, list):
            return result

        # Incluir el partner por defecto de pago en el dominio para que se cargue
        result["search_params"]["domain"] = OR([domain, [("id", "=", partner_id.id)]])
        return result
