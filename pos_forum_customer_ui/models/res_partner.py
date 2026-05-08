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
        Valida que la parte nacional del telefono tenga exactamente 8 digitos.
        Solo se ejecuta cuando el guardado proviene del POS.

        Raises:
            ValidationError: Si el numero nacional no tiene 8 digitos.
        """
        if not (self.env.context.get("from_pos") or self.env.context.get("pos_session_id")):
            return

        for partner in self:
            if not partner.country_id:
                continue

            phone_code_str = str(partner.country_id.phone_code) if partner.country_id.phone_code else ""

            for field_name in ["mobile", "phone"]:
                value = getattr(partner, field_name) or ""
                if not value:
                    continue
                digits_only = re.sub(r"\D", "", value)
                national_digits = digits_only[len(phone_code_str):] if phone_code_str and digits_only.startswith(phone_code_str) else digits_only
                if len(national_digits) != 8:
                    raise ValidationError(_("Phone must be 8 digits."))

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
    def pos_consultar_rut(self, partner_id, identification_type_id=False):
        """
        Consulta DGI sobre un partner ya existente reusando el mismo metodo
        que se ejecuta desde el backend (``get_partner_dgi_data`` definido en
        ``l10n_uy_einvoice_uruware``). El metodo persiste los datos en el
        partner via ``load_dgi_data`` -> ``write``.

        Args:
            partner_id (int): ID del partner a consultar.
            identification_type_id (int|False): Tipo de identificacion seleccionado
                en el formulario del POS. Se aplica antes de la consulta para que
                DGI valide el documento contra el tipo correcto.

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

        # Sincronizar tipo de identificacion desde el formulario del POS antes
        # de consultar, para que DGI valide contra el tipo correcto y no el que
        # tenia el partner en la BD (que podria ser CI u otro).
        if identification_type_id and partner.l10n_latam_identification_type_id.id != identification_type_id:
            partner.write({"l10n_latam_identification_type_id": identification_type_id})

        # Ejecutar consulta DGI; persiste valores via partner.write() interno
        partner.get_partner_dgi_data()

        # Retornar campos para refrescar el formulario del POS
        return partner.read(self._POS_RUT_FIELDS)[0]

    @api.model
    def pos_consultar_rut_preview(self, vat, identification_type_id=False):
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
            identification_type_id (int|False): Tipo de identificacion seleccionado
                en el formulario del POS. Se incluye en el create para que DGI
                valide el documento contra el tipo correcto y no asuma CI.

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

        # Crear partner minimo con el VAT y el tipo de identificacion seleccionado
        # en el POS, para que DGI valide el documento contra el tipo correcto.
        vals = {"name": vat, "vat": vat}
        if identification_type_id:
            vals["l10n_latam_identification_type_id"] = identification_type_id

        partner = Partner.with_context(from_pos=True).create(vals)

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
