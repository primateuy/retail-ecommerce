# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_re


class _PosRutPreviewRollback(Exception):
    """Excepcion interna de control de flujo para la consulta RUT del POS.

    Se lanza luego de capturar los datos DGI para revertir el savepoint y
    descartar el partner temporal. Nunca se propaga al usuario.
    """


class ResPartner(models.Model):
    _inherit = "res.partner"

    pos_fe_amount_limit_control = fields.Boolean(
        string="Control de monto máximo permitido FE",
        help="Habilita el control de un monto máximo permitido por comprobante "
        "de facturación electrónica para este cliente en el POS.",
    )
    pos_fe_max_amount_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda monto total",
        default=lambda self: self.env.company.currency_id,
    )
    pos_fe_max_amount = fields.Monetary(
        string="Monto total permitido",
        currency_field="pos_fe_max_amount_currency_id",
    )
    company_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda compañía",
        compute="_compute_company_currency_id",
    )
    pos_fe_max_amount_company_currency = fields.Monetary(
        string="Monto total moneda compañía",
        compute="_compute_pos_fe_max_amount_company_currency",
        currency_field="company_currency_id",
        store=True,
    )

    @api.depends_context("company")
    def _compute_company_currency_id(self):
        """Expone la moneda de la compañía activa como campo de apoyo.

        Se usa como ``currency_field`` de ``pos_fe_max_amount_company_currency``
        para que el widget monetario muestre el símbolo correcto.
        """
        company_currency = self.env.company.currency_id
        for partner in self:
            partner.company_currency_id = company_currency

    @api.depends(
        "pos_fe_max_amount",
        "pos_fe_max_amount_currency_id",
        "company_currency_id.rate_ids.rate",
    )
    def _compute_pos_fe_max_amount_company_currency(self):
        """Convierte el monto máximo permitido a la moneda de la compañía.

        Se recalcula ademas cuando se agrega una nueva cotizacion en
        ``res.currency.rate`` para la moneda de la compañia
        (``company_currency_id``), para que el monto convertido no quede
        desactualizado frente al tipo de cambio vigente.

        Returns:
            None: Asigna el valor convertido en ``pos_fe_max_amount_company_currency``.
        """
        company = self.env.company
        today = fields.Date.context_today(self)
        for partner in self:
            if partner.pos_fe_max_amount_currency_id:
                partner.pos_fe_max_amount_company_currency = partner.pos_fe_max_amount_currency_id._convert(
                    partner.pos_fe_max_amount, company.currency_id, company, today
                )
            else:
                partner.pos_fe_max_amount_company_currency = partner.pos_fe_max_amount

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
            # Empresas no tienen restricción de formato en teléfono/celular.
            if partner.is_company:
                continue
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
        hace ``partner.write(...)``. Por eso se crea un partner minimo dentro de
        un savepoint que SIEMPRE se revierte: los datos consultados viajan al
        formulario del POS y el partner real se crea una unica vez cuando el
        cajero confirma el guardado (``create_from_ui``). Asi la consulta no
        deja contactos huerfanos en el backend si el alta se cancela.

        Args:
            vat (str): Numero de documento a consultar.
            identification_type_id (int|False): Tipo de identificacion seleccionado
                en el formulario del POS. Se incluye en el create para que DGI
                valide el documento contra el tipo correcto y no asuma CI.

        Returns:
            dict: Campos del partner (sin ``id``) para el POS.
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

        data = {}
        try:
            with self.env.cr.savepoint():
                partner = Partner.with_context(from_pos=True).create(vals)
                # Ejecutar consulta DGI sobre el partner temporal
                partner.get_partner_dgi_data()
                data = partner.read(self._POS_RUT_FIELDS)[0]
                # Revertir el savepoint: la consulta es solo lectura para el
                # POS y el partner temporal no debe quedar persistido.
                raise _PosRutPreviewRollback()
        except _PosRutPreviewRollback:
            # Descartar cache que quedo apuntando al partner revertido
            self.env.invalidate_all()

        # Sin ``id``: el POS crea el partner una sola vez al guardar
        data.pop("id", None)
        return data

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
