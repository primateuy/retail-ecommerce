# -*- coding: utf-8 -*-
import re

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_re


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.constrains("mobile", "phone", "country_id")
    def _check_pos_phone_format(self):
        """
        Valida el formato de telefono segun configuracion del pais.

        Raises:
            ValidationError: Si el telefono no cumple el formato o largo.
        """
        for partner in self:
            # Saltar validacion si no hay pais configurado
            if not partner.country_id:
                continue

            # Preparar regex y longitud si existen en el pais
            phone_regex = self._get_pos_phone_regex(partner.country_id.pos_phone_format)
            phone_length = partner.country_id.pos_phone_length or 0

            # Validar solo si hay configuracion activa
            if not phone_regex and not phone_length:
                continue

            # Validar los campos de telefono relevantes
            for field_name in ["mobile", "phone"]:
                value = getattr(partner, field_name) or ""
                if not value:
                    continue
                # Normalizar solo digitos para validar largo
                digits_only = re.sub(r"\D", "", value)
                if phone_length and len(digits_only) != phone_length:
                    raise ValidationError(
                        _("Phone length must be %s digits for this country.") % phone_length
                    )
                if phone_regex and not re.fullmatch(phone_regex, value):
                    raise ValidationError(
                        _("Phone format does not match the required pattern.")
                    )

    @api.constrains("email")
    def _check_pos_email_format(self):
        """
        Valida formato de email si el valor fue ingresado.

        Raises:
            ValidationError: Si el email no cumple el formato.
        """
        for partner in self:
            if partner.email and not email_re.match(partner.email):
                raise ValidationError(_("Email format is invalid."))

    def _get_pos_phone_regex(self, phone_format):
        """
        Convierte un formato simple a una expresion regular.

        Args:
            phone_format (str): Formato de telefono, ejemplo "09x xxx xxx".

        Returns:
            str|None: Regex compilable o None si no hay formato.
        """
        # Retornar None si no hay formato
        if not phone_format:
            return None

        # Construir regex base a partir del formato
        regex_parts = []
        for char in phone_format:
            if char in ("x", "X"):
                regex_parts.append(r"\d")
            elif char.isdigit():
                regex_parts.append(re.escape(char))
            elif char.isspace():
                regex_parts.append(r"\s?")
            else:
                regex_parts.append(re.escape(char))

        # Forzar coincidencia completa
        return "^" + "".join(regex_parts) + "$"

    @api.model
    def pos_consultar_rut(self, partner_id):
        """
        Consulta datos de RUT y devuelve los campos relevantes para POS.

        Args:
            partner_id (int): ID del partner a consultar.

        Returns:
            dict: Datos del partner actualizados para el POS.
        """
        # Validar que exista el partner
        partner = self.browse(partner_id).exists()
        if not partner:
            raise UserError(_("Partner not found for RUT query."))

        # Validar que el metodo de consulta exista
        if not hasattr(partner, "_consultar_partner_ruc"):
            raise UserError(_("RUT query is not available on this system."))

        # Validar que el partner tenga numero de documento
        if not partner.vat:
            raise UserError(_("Document number is required to query RUT."))

        # Ejecutar consulta y actualizar el partner
        partner._consultar_partner_ruc()

        # Retornar campos necesarios para refrescar en POS
        fields_to_read = [
            "name",
            "social_reason",
            "street",
            "street2",
            "city",
            "state_id",
            "country_id",
            "zip",
            "phone",
            "mobile",
            "email",
            "vat",
            "is_company",
            "company_type",
        ]
        return partner.read(fields_to_read)[0]

    @api.model
    def pos_consultar_rut_preview(self, vat):
        """
        Consulta datos de RUT sin guardar el partner en base.

        Esta funcion permite validar/consultar el RUT desde el POS
        antes de guardar el cliente, devolviendo los datos para
        completar la pantalla en frontend.

        Args:
            vat (str): Numero de documento a consultar.

        Returns:
            dict: Datos del partner resultante para el POS.
        """
        # Validar que exista numero de documento
        if not vat:
            raise UserError(_("Document number is required to query RUT."))

        # Preparar un registro en memoria para evitar guardado
        partner = self.new({"vat": vat})

        # Validar que el metodo de consulta exista en el sistema
        if not hasattr(partner, "_consultar_partner_ruc"):
            raise UserError(_("RUT query is not available on this system."))

        # Ejecutar consulta y poblar datos en memoria
        partner._consultar_partner_ruc()

        # Preparar campos relevantes para refrescar en POS
        fields_to_read = [
            "name",
            "social_reason",
            "street",
            "street2",
            "city",
            "state_id",
            "country_id",
            "zip",
            "phone",
            "mobile",
            "email",
            "vat",
            "is_company",
            "company_type",
        ]

        # Retornar valores desde cache del registro en memoria
        return partner.read(fields_to_read)[0]
