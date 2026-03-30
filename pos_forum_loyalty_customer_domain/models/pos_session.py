# -*- coding: utf-8 -*-
"""
Carga de datos POS para reglas con dominio de cliente y lista blanca de campos.

El documento Forum pide que solo se usen en el dominio campos que viajan al
cache del TPV; esa lista se centraliza aquí y se reutiliza en la restricción de
``loyalty.rule``.
"""

import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


def _forum_domain_to_jsonable(obj):
    """
    Convierte tuplas del dominio Odoo a listas para serializar en JSON.

    Args:
        obj: Nodo del dominio (lista, tupla o escalar).

    Returns:
        Estructura serializable con ``json.dumps``.
    """
    if isinstance(obj, tuple):
        return [_forum_domain_to_jsonable(item) for item in obj]
    if isinstance(obj, list):
        return [_forum_domain_to_jsonable(item) for item in obj]
    return obj


class PosSession(models.Model):
    """Extiende la sesión POS con campos de lealtad y de partner para dominios."""

    _inherit = "pos.session"

    @api.model
    def _forum_pos_allowed_partner_domain_field_names(self):
        """
        Devuelve los nombres de campo de ``res.partner`` permitidos en dominios POS.

        Incluye el conjunto que Odoo envía por defecto al POS más extensiones
        habituales en Forum (categoría, padre, fechas de nacimiento si existen).

        Returns:
            frozenset[str]: Nombres de campo permitidos.
        """
        # Bloque: campos del cargador estándar de partners en point_of_sale (17).
        base = {
            "name",
            "street",
            "city",
            "state_id",
            "country_id",
            "vat",
            "lang",
            "phone",
            "zip",
            "mobile",
            "email",
            "barcode",
            "write_date",
            "property_account_position_id",
            "property_product_pricelist",
            "parent_name",
            "category_id",
            "parent_id",
        }
        Partner = self.env["res.partner"]
        # Bloque: campos extra que otros módulos Forum suelen cargar al POS.
        optional = (
            "birthdate_date",
            "birthdate",
            "l10n_latam_identification_type_id",
            "social_reason",
            "company_type",
            "firstname",
            "lastname",
            "default_partner_street",
            "default_partner_city",
        )
        for fname in optional:
            if fname in Partner._fields:
                base.add(fname)
        return frozenset(base)

    def _loader_params_loyalty_rule(self):
        """
        Incluye ``customer_domain`` en las reglas de lealtad enviadas al cliente.

        Returns:
            dict: Parámetros de búsqueda extendidos para ``loyalty.rule``.
        """
        result = super()._loader_params_loyalty_rule()
        search = result.get("search_params")
        if not search or not isinstance(search.get("fields"), list):
            return result
        if "customer_domain" not in search["fields"]:
            search["fields"].append("customer_domain")
        return result

    def _loader_params_res_partner(self):
        """
        Asegura ``category_id`` (y ``parent_id``) en partners cargados al POS.

        Si ``fields`` está vacío no se modifica (significa «todos los campos»).

        Returns:
            dict: Parámetros de búsqueda extendidos para ``res.partner``.
        """
        result = super()._loader_params_res_partner()
        search = result.get("search_params")
        if (
            not search
            or not isinstance(search.get("fields"), list)
            or len(search["fields"]) == 0
        ):
            return result
        partner_fields = self.env["res.partner"]._fields
        for fname in ("category_id", "parent_id"):
            if fname in partner_fields and fname not in search["fields"]:
                search["fields"].append(fname)
        return result

    def _get_pos_ui_loyalty_rule(self, params):
        """
        Normaliza ``customer_domain`` a JSON para el cliente POS.

        El widget de backend puede persistir el dominio como literal Python;
        ``JSON.parse`` en el TPV fallaría. Tras parsear de forma segura, se
        re-serializa en JSON estándar.

        Returns:
            list[dict]: Reglas como ``search_read``, con dominios normalizados.
        """
        rules = super()._get_pos_ui_loyalty_rule(params)
        LoyaltyRule = self.env["loyalty.rule"]
        for rule in rules:
            cd = rule.get("customer_domain")
            if not cd or str(cd).strip() in ("", "[]", "null"):
                continue
            try:
                virtual = LoyaltyRule.new({"customer_domain": cd})
                domain = virtual._forum_parse_customer_domain()
                rule["customer_domain"] = json.dumps(_forum_domain_to_jsonable(domain))
            except Exception:
                _logger.warning(
                    "pos_forum_loyalty_customer_domain: no se normalizó "
                    "customer_domain para loyalty.rule id=%s",
                    rule.get("id"),
                    exc_info=True,
                )
        return rules
