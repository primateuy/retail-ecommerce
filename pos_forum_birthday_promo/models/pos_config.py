# -*- coding: utf-8 -*-
"""
Extiende la configuración del Punto de Venta con los parámetros de la promoción
por cumpleaños (ventana de días, porcentaje, producto de línea, primera orden y
límite opcional de usos en el período).
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    """
    Campos de promoción cumpleaños para el POS.

    Se usa junto con `partner_contact_birthdate` (campo `birthdate_date`) y un
    programa de lealtad técnico para exponer `reward_id` en la línea de descuento.
    """

    _inherit = "pos.config"

    forum_birthday_promo_active = fields.Boolean(
        string="Promoción cumpleaños (POS)",
        help="Si está activo, el POS puede aplicar un descuento automático cuando "
        "el cliente está en la ventana de cumpleaños y cumple las reglas.",
    )
    forum_birthday_discount_percent = fields.Float(
        string="Porcentaje de descuento",
        default=0.0,
        help="Porcentaje aplicado sobre el total con impuestos incluidos de las "
        "líneas normales del pedido (coherente con el TPV en precios con impuestos "
        "incluidos). No incluye otras líneas de recompensa.",
    )
    forum_birthday_tolerance_days = fields.Integer(
        string="Tolerancia (días)",
        default=0,
        help="Días antes y después del aniversario (mismo número en ambos sentidos). "
        "Ejemplo: 10 = desde 10 días antes hasta 10 días después.",
    )
    forum_birthday_first_order_only = fields.Boolean(
        string="Solo primera orden del día",
        help="Si está activo, solo aplica si el cliente no tiene órdenes POS "
        "finalizadas en la fecha actual del servidor.",
    )
    forum_birthday_max_uses_per_period = fields.Integer(
        string="Máximo usos con descuento en el período",
        default=0,
        help="Tope de compras con línea de esta promo durante la ventana de "
        "tolerancia (± días respecto al cumpleaños en el año en curso), solo en "
        "este punto de venta. Use 0 o deje vacío para no limitar por cantidad "
        "de usos (sigue aplicando ventana de fechas y, si aplica, solo primera "
        "orden del día).",
    )
    forum_birthday_product_id = fields.Many2one(
        "product.product",
        string="Producto de la promoción",
        domain="[('available_in_pos', '=', True), ('sale_ok', '=', True)]",
        default=lambda self: self.env.ref(
            "pos_forum_birthday_promo.product_forum_birthday_discount_line",
            raise_if_not_found=False,
        ),
        help="Producto que aparece como línea de descuento al final del pedido.",
    )
    forum_birthday_reward_id = fields.Many2one(
        "loyalty.reward",
        string="Recompensa lealtad (técnico)",
        compute="_compute_forum_birthday_reward_id",
        store=False,
        help="Recompensa creada por el módulo para etiquetar la línea con reward_id.",
    )

    @api.depends()
    def _compute_forum_birthday_reward_id(self):
        """
        Resuelve la recompensa técnica instalada por xmlid (post_init_hook).

        No almacenado: se recalcula al leer la configuración para el POS.
        """
        reward = self.env.ref(
            "pos_forum_birthday_promo.loyalty_reward_forum_birthday",
            raise_if_not_found=False,
        )
        rid = reward.id if reward else False
        for config in self:
            config.forum_birthday_reward_id = rid

    @api.constrains(
        "forum_birthday_promo_active",
        "forum_birthday_discount_percent",
        "forum_birthday_tolerance_days",
        "forum_birthday_product_id",
        "forum_birthday_max_uses_per_period",
    )
    def _check_forum_birthday_settings(self):
        """
        Valida que, si la promo está activa, existan valores mínimos coherentes.
        """
        for config in self:
            if not config.forum_birthday_promo_active:
                continue
            # Bloque: porcentaje y tolerancia obligatorios cuando la promo está activa.
            if config.forum_birthday_discount_percent <= 0:
                raise ValidationError(
                    _("El porcentaje de descuento debe ser mayor que cero.")
                )
            if config.forum_birthday_tolerance_days < 0:
                raise ValidationError(_("La tolerancia en días no puede ser negativa."))
            if not config.forum_birthday_product_id:
                raise ValidationError(
                    _("Debe indicarse el producto de la promoción de cumpleaños.")
                )
            # Bloque: el tope de usos no puede ser negativo (0 = sin límite de usos).
            if config.forum_birthday_max_uses_per_period < 0:
                raise ValidationError(
                    _("El máximo de usos en el período no puede ser negativo.")
                )
