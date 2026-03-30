# -*- coding: utf-8 -*-
"""
Validación del dominio de cliente cuando el programa de lealtad aplica en TPV.
"""

import ast
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LoyaltyRule(models.Model):
    """Restringe campos del dominio de cliente para programas con ``pos_ok``."""

    _inherit = "loyalty.rule"

    program_pos_ok = fields.Boolean(
        string="Programa disponible en TPV",
        related="program_id.pos_ok",
        readonly=True,
        help="Indica si el programa está habilitado para Punto de venta.",
    )

    def _forum_parse_customer_domain(self):
        """
        Interpreta ``customer_domain`` tal como lo guarda el widget de Odoo.

        El campo Char suele almacenar JSON con comillas dobles o un literal
        Python (tuplas y comillas simples). ``json.loads`` falla en el segundo
        caso; se usa ``ast.literal_eval`` como respaldo seguro.

        Returns:
            list | tuple: Dominio listo para recorrer.

        Raises:
            ValidationError: Si no se puede interpretar.
        """
        self.ensure_one()
        raw = (self.customer_domain or "").strip()
        if not raw or raw == "[]":
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError) as err:
            raise ValidationError(
                _(
                    "El dominio de cliente no tiene un formato válido (ni JSON ni "
                    "literal Python permitido por literal_eval): %s"
                )
                % err
            ) from err

    @api.constrains("customer_domain", "program_id")
    def _check_forum_pos_customer_domain_fields(self):
        """
        Valida que el dominio solo use campos cargados en el POS si ``pos_ok``.

        Si el programa no está en TPV, no se aplica la restricción (ventas/web
        pueden usar el dominio completo del modelo).
        """
        PosSession = self.env["pos.session"]
        allowed = PosSession._forum_pos_allowed_partner_domain_field_names()
        for rule in self:
            if not rule.program_id or not rule.program_id.pos_ok:
                continue
            if not rule.customer_domain or rule.customer_domain in ("[]", "null"):
                continue
            domain = rule._forum_parse_customer_domain()
            used = rule._forum_extract_domain_field_names(domain)
            invalid = used - allowed
            if invalid:
                raise ValidationError(
                    _(
                        "Para programas con Punto de venta, el dominio de cliente solo "
                        "puede usar campos que el POS carga en el cliente. "
                        "Campos no permitidos: %s. "
                        "Campos permitidos incluyen, entre otros: categoría de cliente "
                        "(category_id), país, provincia, VAT, email, teléfono, "
                        "fecha de nacimiento si está instalada, etc."
                    )
                    % ", ".join(sorted(invalid))
                )

    def _forum_extract_domain_field_names(self, domain):
        """
        Recolecta nombres de campo de hojas del dominio (sin operadores lógicos).

        Args:
            domain (list | tuple): Dominio en formato Odoo.

        Returns:
            set[str]: Nombres de campo (primer segmento si hay punto).
        """
        names = set()

        def walk(node):
            if not node:
                return
            if isinstance(node, (list, tuple)):
                if (
                    len(node) == 3
                    and isinstance(node[0], str)
                    and node[0] not in ("|", "&", "!")
                ):
                    field_name = node[0].split(".", 1)[0]
                    names.add(field_name)
                else:
                    for item in node:
                        walk(item)

        walk(domain)
        return names
