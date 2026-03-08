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
        Solo se ejecuta cuando el guardado proviene del POS (context from_pos
        o pos_session_id), para no afectar clientes creados/editados en backend.
        Considera codigo de pais: se valida la parte nacional del numero.

        Raises:
            ValidationError: Si el telefono no cumple el formato o largo.
        """
        # Ejecutar validacion solo cuando viene del POS
        if not (self.env.context.get("from_pos") or self.env.context.get("pos_session_id")):
            return

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

            # Codigo de pais para normalizar numero (quitar prefijo antes de validar)
            phone_code = partner.country_id.phone_code
            phone_code_str = str(phone_code) if phone_code else ""

            # Validar los campos de telefono relevantes
            for field_name in ["mobile", "phone"]:
                value = getattr(partner, field_name) or ""
                if not value:
                    continue
                # Normalizar a solo digitos y obtener parte nacional (sin codigo de pais)
                digits_only = re.sub(r"\D", "", value)
                if phone_code_str and digits_only.startswith(phone_code_str):
                    national_digits = digits_only[len(phone_code_str) :]
                else:
                    national_digits = digits_only
                # Validar longitud de la parte nacional
                if phone_length and len(national_digits) != phone_length:
                    raise ValidationError(
                        _("Largo de número debe ser %s digitos para el país seleccionado.") % phone_length
                    )
                # Obtener parte nacional para validar formato (quitar + y codigo pais)
                national_value = value.strip()
                if phone_code_str and national_value.startswith("+"):
                    rest = national_value[1:].lstrip()
                    if rest.startswith(phone_code_str):
                        national_value = rest[len(phone_code_str) :].lstrip()
                    else:
                        national_value = rest
                if phone_regex and not re.fullmatch(phone_regex, national_value):
                    raise ValidationError(
                        _("Formato de Celular incorrecto.")
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
            raise UserError(_("RUT Consultado no hallado"))

        # Validar que el metodo de consulta exista
        if not hasattr(partner, "_consultar_partner_ruc"):
            raise UserError(_("Consulta RUT no disponible"))

        # Validar que el partner tenga numero de documento
        if not partner.vat:
            raise UserError(_("Es necesario un número de RUT para ejecutar la consulta"))

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
            raise UserError(_("Consulta RUT no está disponible"))

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

    @api.model
    def create_from_pos(self, vals):
        """
        Crea un partner desde el POS con contexto from_pos para que
        la validacion de telefono se aplique y considere codigo de pais.
        """
        return self.with_context(from_pos=True).create(vals)

    @api.model
    def write_from_pos(self, partner_id, vals):
        """
        Actualiza un partner desde el POS con contexto from_pos para que
        la validacion de telefono se aplique y considere codigo de pais.

        Args:
            partner_id (int): ID del partner a actualizar.
            vals (dict): Valores a escribir.
        """
        return self.browse(partner_id).with_context(from_pos=True).write(vals)
