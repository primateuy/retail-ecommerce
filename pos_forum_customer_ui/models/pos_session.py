# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _pos_ui_models_to_load(self):
        """
        Extiende los modelos a cargar para incluir tipos de identificacion.

        Returns:
            list: Lista de modelos a cargar en la UI del POS.
        """
        # Obtener la lista base de modelos
        result = super()._pos_ui_models_to_load()
        # Agregar el modelo de tipos de identificacion si no existe
        if "l10n_latam.identification.type" not in result:
            result.append("l10n_latam.identification.type")
        # Retornar el listado final
        return result

    def _loader_params_l10n_latam_identification_type(self):
        """
        Define los parametros de carga para tipos de identificacion.

        Returns:
            dict: Parametros de busqueda para el modelo l10n_latam.identification.type.
        """
        # Preparar el dominio y campos minimos
        return {
            "search_params": {
                "domain": [],
                "fields": ["name", "code", "country_id", "check_number", "check_type", "is_vat", "company_type"],
            },
        }

    def _get_pos_ui_l10n_latam_identification_type(self, params):
        """
        Obtiene los tipos de identificacion para el POS.

        Args:
            params (dict): Parametros de busqueda con dominio y campos.

        Returns:
            list: Tipos de identificacion en formato search_read.
        """
        # Ejecutar la busqueda segun parametros
        return self.env["l10n_latam.identification.type"].search_read(**params["search_params"])

    def _loader_params_pos_config(self):
        """
        Extiende la carga de pos.config con valores por defecto de clientes.

        Returns:
            dict: Parametros de carga extendidos para pos.config.
        """
        # Obtener parametros base del POS
        result = super()._loader_params_pos_config()
        # Validar estructura antes de modificar
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
            and len(result["search_params"]["fields"]) > 0
        ):
            # Agregar campos si no existen
            for field_name in ["default_partner_street", "default_partner_city"]:
                if field_name not in result["search_params"]["fields"]:
                    result["search_params"]["fields"].append(field_name)
        # Retornar parametros extendidos
        return result

    def _loader_params_res_country(self):
        """
        Extiende la carga de paises con validaciones de telefono.

        Returns:
            dict: Parametros de carga extendidos para res.country.
        """
        # Obtener parametros base del POS
        result = super()._loader_params_res_country()
        # Validar estructura antes de modificar
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
        ):
            # Agregar campos de validacion y codigo de pais para telefono
            extra_fields = ["pos_phone_length", "pos_phone_format", "phone_code"]
            for field_name in extra_fields:
                if field_name not in result["search_params"]["fields"]:
                    result["search_params"]["fields"].append(field_name)
        # Retornar parametros extendidos
        return result

    def _loader_params_res_partner(self):
        """
        Extiende la carga de clientes con campos usados en el POS.

        Returns:
            dict: Parametros de carga extendidos para res.partner.
        """
        # Obtener parametros base del POS
        result = super()._loader_params_res_partner()
        # Validar estructura antes de modificar
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
        ):
            # Agregar campos requeridos por la UI de clientes
            extra_fields = [
                "l10n_latam_identification_type_id",
                "birthdate_date",
                "social_reason",
                "company_type",
            ]
            for field_name in extra_fields:
                if field_name not in result["search_params"]["fields"]:
                    result["search_params"]["fields"].append(field_name)

            # Agregar firstname/lastname solo si existen en el modelo
            partner_fields = self.env["res.partner"]._fields
            for field_name in ["firstname", "lastname"]:
                if field_name in partner_fields and field_name not in result["search_params"]["fields"]:
                    result["search_params"]["fields"].append(field_name)
        # Retornar parametros extendidos
        return result

    def _pos_data_process(self, loaded_data):
        """
        Inyecta banderas adicionales en la data del POS.

        Args:
            loaded_data (dict): Data cargada para el POS.
        """
        # Ejecutar procesamiento base
        super()._pos_data_process(loaded_data)

        # Informar si partner_firstname esta disponible
        partner_fields = self.env["res.partner"]._fields
        loaded_data["partner_firstname_enabled"] = all(
            field_name in partner_fields for field_name in ["firstname", "lastname"]
        )
