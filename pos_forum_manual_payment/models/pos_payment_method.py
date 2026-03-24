# -*- coding: utf-8 -*-
"""
Extensión de pos.payment.method para pagos manuales POS.

Este modelo agrega banderas y relaciones necesarias para:
- Marcar métodos de pago que deben crear transacciones manuales.
- Asociar un proveedor de pago manual.
- Habilitar la creación de cheques estándar cuando corresponda.
- Serializar la configuración de campos del popup del POS en JSON.
"""

import json

from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    """
    Extensión del modelo pos.payment.method para pagos manuales.

    Los campos definidos aquí permiten configurar, por cada método de pago
    del POS, si debe disparar la creación de una transacción manual en
    payment.transaction y si debe habilitar la lógica de cheques estándar.
    """

    _inherit = "pos.payment.method"

    manual_transaction_enabled = fields.Boolean(
        string="Crear transacciones manuales",
        help=(
            "Si está activo, al utilizar este método de pago en el POS se "
            "deberá crear una transacción manual en payment.transaction."
        ),
    )
    manual_provider_id = fields.Many2one(
        comodel_name="payment.provider",
        string="Proveedor manual",
        domain=[("manual_pos_provider", "=", True)],
        help=(
            "Proveedor de pago que se utilizará para generar las "
            "transacciones manuales asociadas a este método de pago."
        ),
    )
    manual_create_checks = fields.Boolean(
        string="Crear cheques estándar",
        help=(
            "Si está activo y el diario asociado está configurado para "
            "cheques estándar, se deberá habilitar la creación de cheques "
            "en el backend utilizando l10n_latam_check."
        ),
    )
    manual_payment_popup_config = fields.Text(
        string="Configuración popup manual (JSON)",
        compute="_compute_manual_payment_popup_config",
        help=(
            "Lista JSON de campos a mostrar en el POS para transacciones "
            "manuales, según el proveedor y la tabla de configuración."
        ),
    )

    @api.depends(
        "manual_transaction_enabled",
        "manual_provider_id",
        "manual_provider_id.manual_field_config_ids",
        "manual_provider_id.manual_field_config_ids.sequence",
        "manual_provider_id.manual_field_config_ids.request_field_id",
        "manual_provider_id.manual_field_config_ids.required",
        "manual_provider_id.manual_field_config_ids.default_char_value",
        "manual_provider_id.manual_field_config_ids.default_reference",
        "manual_provider_id.payment_method_ids",
    )
    def _compute_manual_payment_popup_config(self):
        """
        Genera el JSON de campos del popup para el frontend del POS.

        Incluye tipo de campo, etiqueta, obligatoriedad, valores por defecto
        y opciones para relaciones many2one (marcas de tarjeta).
        """
        for rec in self:
            if not rec.manual_transaction_enabled or not rec.manual_provider_id:
                rec.manual_payment_popup_config = "[]"
                continue
            lines = rec._build_manual_payment_popup_field_lines()
            rec.manual_payment_popup_config = json.dumps(lines)

    def _build_manual_payment_popup_field_lines(self):
        """
        Construye la lista de diccionarios enviada al POS.

        Cada entrada describe un campo a capturar según la configuración
        del proveedor manual asociado al método de pago.
        """
        self.ensure_one()
        provider = self.manual_provider_id
        lines = []
        for config_line in provider.manual_field_config_ids.sorted("sequence"):
            request_field = config_line.request_field_id
            if not request_field:
                continue
            entry = {
                "code": request_field.code,
                "label": request_field.name,
                "field_type": request_field.field_type,
                "required": config_line.required,
            }
            if request_field.field_type == "char":
                entry["default"] = config_line.default_char_value or ""
                if request_field.code == "holder_name" and (
                    (config_line.default_char_value or "").strip() == "partner_name"
                ):
                    entry["special_default"] = "partner_name"
            elif request_field.field_type == "many2one":
                relation_model = (
                    request_field.relation_model_id.model
                    if request_field.relation_model_id
                    else False
                )
                entry["relation_model"] = relation_model
                entry["default_id"] = (
                    config_line.default_reference.id if config_line.default_reference else False
                )
                if relation_model == "payment.method":
                    entry["options"] = self._get_payment_method_brand_options(provider)
            lines.append(entry)
        return lines

    def _get_payment_method_brand_options(self, provider):
        """
        Obtiene las marcas (VISA, OCA, etc.) asociadas al método Card.

        Se listan los registros payment.method hijos del método primario Card
        enlazados al proveedor o, en su defecto, el Card global del sistema.
        """
        payment_method_model = self.env["payment.method"].sudo()
        card_methods = provider.payment_method_ids.filtered(lambda m: m.code == "card")
        if not card_methods:
            card_methods = payment_method_model.search([("code", "=", "card")], limit=1)
        if not card_methods:
            return []
        brands = payment_method_model.search(
            [("primary_payment_method_id", "in", card_methods.ids)],
            order="name asc",
        )
        return [{"id": brand.id, "name": brand.name} for brand in brands]

