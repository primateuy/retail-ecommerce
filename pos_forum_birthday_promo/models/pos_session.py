# -*- coding: utf-8 -*-
"""
Carga de datos en el POS y comprobación server-side de elegibilidad de la promo.
"""

from datetime import datetime, time

from odoo import api, fields, models


class PosSession(models.Model):
    """
    Extiende la sesión POS para exponer campos de configuración y un RPC de
    elegibilidad que respeta fecha servidor y regla de primera orden.
    """

    _inherit = "pos.session"

    def _loader_params_res_partner(self):
        """
        Garantiza que lleguen al POS las fechas de nacimiento usadas por la promo.

        Se incluyen ``birthdate_date`` (OCA) y ``birthdate`` (p. ej. módulos de
        terceros) si existen en el modelo. Si ``fields`` está vacío, no se toca
        (comportamiento «todos los campos» del POS).

        Returns:
            dict: Parámetros de búsqueda de partners extendidos.
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
        for fname in ("birthdate_date", "birthdate"):
            if fname in partner_fields and fname not in search["fields"]:
                search["fields"].append(fname)
        return result

    def _loader_params_pos_config(self):
        """
        Añade a la carga del `pos.config` los campos usados por el cliente POS.

        Si ``fields`` es una lista vacía, el estándar del POS significa «cargar
        todos los campos»; no se debe añadir nada, porque al pasar a no vacía
        Odoo haría ``search_read`` solo con esos campos y faltarían claves como
        ``is_posbox`` (véase ``_get_pos_ui_pos_config`` en ``point_of_sale``).

        Returns:
            dict: Parámetros de búsqueda extendidos para ``pos.config``.
        """
        result = super()._loader_params_pos_config()
        search = result.get("search_params")
        if (
            not result
            or not isinstance(result, dict)
            or not search
            or "fields" not in search
            or not isinstance(search["fields"], list)
            or len(search["fields"]) == 0
        ):
            return result
        extra = [
            "forum_birthday_promo_active",
            "forum_birthday_discount_percent",
            "forum_birthday_tolerance_days",
            "forum_birthday_first_order_only",
            "forum_birthday_product_id",
            "forum_birthday_reward_id",
        ]
        for name in extra:
            if name not in search["fields"]:
                search["fields"].append(name)
        return result

    @api.model
    def forum_birthday_check_eligibility(self, session_id, partner_id):
        """
        Indica si el partner puede recibir la promo en este momento según backend.

        Usa ``birthdate_date`` (OCA) y/o ``birthdate`` (si existe en el modelo):
        la promo aplica si **alguna** de las fechas definidas cae en la ventana
        de tolerancia (mismo criterio ± días respecto al aniversario en el año
        en curso). Opcionalmente exige que no haya órdenes POS finalizadas hoy.

        Args:
            session_id (int): ID de `pos.session` abierta.
            partner_id (int): ID de `res.partner`.

        Returns:
            dict: ``{"eligible": bool}`` y opcionalmente ``"reason"`` para depuración.
        """
        session = self.sudo().browse(session_id)
        if not session.exists():
            return {"eligible": False, "reason": "session"}
        partner = self.env["res.partner"].sudo().browse(partner_id)
        if not partner.exists():
            return {"eligible": False, "reason": "partner"}
        config = session.config_id
        if not config.forum_birthday_promo_active:
            return {"eligible": False, "reason": "inactive"}
        birth_dates = self._forum_birthday_partner_reference_dates(partner)
        if not birth_dates:
            return {"eligible": False, "reason": "no_birthdate"}
        today = fields.Date.context_today(session)
        tolerance = config.forum_birthday_tolerance_days
        if not any(
            self._forum_birthday_date_in_window(bd, today, tolerance)
            for bd in birth_dates
        ):
            return {"eligible": False, "reason": "outside_window"}
        if config.forum_birthday_first_order_only:
            if self._forum_birthday_partner_has_completed_order_today(partner.id, today):
                return {"eligible": False, "reason": "first_order_used"}
        return {"eligible": True}

    def _forum_birthday_partner_reference_dates(self, partner):
        """
        Obtiene las fechas de nacimiento candidatas del contacto (sin duplicar).

        Incluye solo campos que existan en ``res.partner`` y tengan valor.

        Args:
            partner (res.partner): Registro del cliente.

        Returns:
            list[date]: Lista de fechas únicas a evaluar con OR lógico.
        """
        Partner = self.env["res.partner"]
        candidates = []
        for fname in ("birthdate_date", "birthdate"):
            if fname not in Partner._fields:
                continue
            value = partner[fname]
            if value:
                candidates.append(value)
        # Evita evaluar dos veces la misma fecha si ambos campos coinciden.
        seen = set()
        unique = []
        for d in candidates:
            if d not in seen:
                seen.add(d)
                unique.append(d)
        return unique

    def _forum_birthday_date_in_window(self, birth_date, today, tolerance_days):
        """
        Comprueba si `today` cae dentro de ±tolerance_days del cumpleaños del año en curso.

        Args:
            birth_date (date): Fecha de nacimiento del contacto.
            today (date): Fecha contextual (empresa/usuario).
            tolerance_days (int): Días antes y después permitidos.

        Returns:
            bool: True si está en ventana.
        """
        try:
            anniversary = birth_date.replace(year=today.year)
        except ValueError:
            # 29 feb en año no bisiesto -> 28 feb
            anniversary = birth_date.replace(year=today.year, month=2, day=28)
        delta_days = (today - anniversary).days
        return -tolerance_days <= delta_days <= tolerance_days

    def _forum_birthday_partner_has_completed_order_today(self, partner_id, today):
        """
        Detecta si el cliente ya tiene una orden POS finalizada en la fecha dada.

        Args:
            partner_id (int): ID del partner.
            today (date): Día a comprobar (zona contextual Odoo).

        Returns:
            bool: True si existe al menos una orden en estados terminal.
        """
        start_dt = fields.Datetime.to_string(datetime.combine(today, time.min))
        end_dt = fields.Datetime.to_string(datetime.combine(today, time.max))
        PosOrder = self.env["pos.order"].sudo()
        return bool(
            PosOrder.search_count(
                [
                    ("partner_id", "=", partner_id),
                    ("state", "in", ("paid", "done", "invoiced")),
                    ("date_order", ">=", start_dt),
                    ("date_order", "<=", end_dt),
                ],
                limit=1,
            )
        )
