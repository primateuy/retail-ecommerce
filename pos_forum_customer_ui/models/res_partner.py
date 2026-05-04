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
                        _("Phone length must be %s digits for this country.") % phone_length
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

    # Campos que se devuelven al frontend tras una consulta DGI para refrescar
    # el formulario del POS. Incluyen ``id`` implicitamente al usar ``read()``.
    _POS_RUT_FIELDS = [
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

    @api.model
    def pos_consultar_rut(self, partner_id):
        """
        Consulta DGI sobre un partner ya existente reusando el mismo metodo
        que se ejecuta desde el backend (``get_partner_dgi_data`` definido en
        ``l10n_uy_einvoice_uruware``). El metodo persiste los datos en el
        partner via ``load_dgi_data`` -> ``write``.

        Args:
            partner_id (int): ID del partner a consultar.

        Returns:
            dict: Campos del partner actualizados para el POS.
        """
        # Validar que exista el partner
        partner = self.browse(partner_id).exists()
        if not partner:
            raise UserError(_("Partner not found for RUT query."))

        # Validar disponibilidad del metodo (depende de l10n_uy_einvoice_uruware
        # estar instalado en la DB; no se agrega como dependencia hard para que
        # el modulo siga siendo reusable en clientes sin esa localizacion).
        if not hasattr(partner, "get_partner_dgi_data"):
            raise UserError(_("RUT query is not available on this system."))

        # Validar que el partner tenga numero de documento
        if not partner.vat:
            raise UserError(_("Document number is required to query RUT."))

        # Ejecutar consulta DGI; persiste valores via partner.write() interno
        partner.get_partner_dgi_data()

        # Retornar campos para refrescar el formulario del POS
        return partner.read(self._POS_RUT_FIELDS)[0]

    @api.model
    def pos_consultar_rut_preview(self, vat):
        """
        Consulta DGI desde el alta de cliente del POS (cuando aun no hay id).

        ``get_partner_dgi_data`` requiere un registro persistido porque al final
        hace ``partner.write(...)``. Por eso se crea un partner minimo con el VAT
        y se ejecuta la consulta sobre ese registro. El id devuelto se asocia al
        formulario del POS para que el guardado posterior haga update y no cree
        un partner adicional. Si DGI falla, el RPC hace rollback y el partner no
        queda huerfano.

        Args:
            vat (str): Numero de documento a consultar.

        Returns:
            dict: Campos del partner (incluye ``id``) para el POS.
        """
        # Validar numero de documento
        if not vat:
            raise UserError(_("Document number is required to query RUT."))

        Partner = self.env["res.partner"]

        # Validar disponibilidad del metodo en el sistema
        if not hasattr(Partner, "get_partner_dgi_data"):
            raise UserError(_("RUT query is not available on this system."))

        # Crear partner minimo con el VAT (en contexto from_pos para que las
        # validaciones de telefono se apliquen como cualquier alta del POS)
        partner = Partner.with_context(from_pos=True).create({
            "name": vat,
            "vat": vat,
        })

        # Ejecutar consulta DGI sobre el partner creado
        partner.get_partner_dgi_data()

        # Retornar campos (incluye id) para refrescar el formulario del POS
        return partner.read(self._POS_RUT_FIELDS)[0]

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
