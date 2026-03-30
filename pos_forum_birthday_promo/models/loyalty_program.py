# -*- coding: utf-8 -*-
"""
Creación idempotente del programa de lealtad técnico para la promo de cumpleaños.

Se invoca desde XML con ``<function>`` en cada actualización del módulo para no
depender solo de ``post_init_hook`` (que en Odoo 17 solo corre en instalación).
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

PROGRAM_XMLID = "pos_forum_birthday_promo.loyalty_program_forum_birthday"
REWARD_XMLID = "pos_forum_birthday_promo.loyalty_reward_forum_birthday"


class LoyaltyProgram(models.Model):
    """
    Hook de datos para registrar el programa/recompensa técnica con xmlid estable.
    """

    _inherit = "loyalty.program"

    @api.model
    def action_forum_birthday_ensure_technical_program(self):
        """
        Crea el programa y la recompensa si faltan los xmlids del módulo.

        Returns:
            bool: True cuando termina sin error (aunque no cree nada).
        """
        if self.env.ref(PROGRAM_XMLID, raise_if_not_found=False):
            return True
        product = self.env.ref(
            "pos_forum_birthday_promo.product_forum_birthday_discount_line",
            raise_if_not_found=False,
        )
        if not product:
            _logger.warning(
                "pos_forum_birthday_promo: producto de descuento no encontrado; "
                "no se crea programa de lealtad."
            )
            return True
        program = self.sudo().create(
            {
                "name": "Forum POS - Cumpleaños (técnico)",
                "program_type": "promotion",
                "company_id": self.env.company.id,
                "pos_ok": True,
                "trigger": "auto",
                "applies_on": "current",
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "reward_point_amount": 1,
                            "reward_point_mode": "order",
                            "minimum_amount": 999999999.0,
                            "minimum_qty": 0,
                        },
                    )
                ],
                "reward_ids": [
                    (
                        0,
                        0,
                        {
                            "description": "Descuento cumpleaños Forum",
                            "reward_type": "discount",
                            "discount_mode": "percent",
                            "discount": 1,
                            "discount_applicability": "order",
                            "required_points": 999999.0,
                            "discount_line_product_id": product.id,
                        },
                    )
                ],
            }
        )
        reward = program.reward_ids[:1]
        if not reward:
            _logger.error(
                "pos_forum_birthday_promo: programa sin recompensa (id=%s).",
                program.id,
            )
            return True
        self.env["ir.model.data"]._update_xmlids(
            [
                {
                    "xml_id": PROGRAM_XMLID,
                    "record": program,
                    "noupdate": True,
                },
                {
                    "xml_id": REWARD_XMLID,
                    "record": reward,
                    "noupdate": True,
                },
            ]
        )
        _logger.info(
            "pos_forum_birthday_promo: programa de lealtad técnico creado (id=%s).",
            program.id,
        )
        return True
