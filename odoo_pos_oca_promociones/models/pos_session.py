# -*- coding: utf-8 -*-
"""
Sesión POS: snapshot de programas de lealtad aplicados en el carrito antes del cobro OCA.

El borrador pos.order a veces aún no existe en el servidor cuando arranca el pago; el cliente
POS guarda aquí los loyalty.program detectados en las líneas del carrito para que el hilo
que lee la tarjeta pueda validar incompatibilidades con payment.method.promotion.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    oca_applied_loyalty_program_ids = fields.Char(
        string="OCA promos: programas de lealtad en carrito (CSV)",
        help="IDs de loyalty.program en el carrito del POS web, "
        "actualizado antes de cada intento de cobro OCA con promociones.",
    )

    def oca_promociones_set_cart_loyalty_programs(self, loyalty_program_ids):
        """
        Persiste los loyalty.program del carrito actual (llamado desde el POS antes de enviar_pago).

        Args:
            loyalty_program_ids (list|tuple|str|False): IDs numéricos o CSV de IDs.

        Returns:
            bool: True si se guardó o limpió correctamente.
        """
        self.ensure_one()
        session = self.sudo()
        _logger.info(
            "OCA_PROMOS_SESSION: oca_promociones_set_cart_loyalty_programs | session_id=%s | "
            "uid=%s | raw_type=%s | raw_repr=%s",
            session.id,
            self.env.uid,
            type(loyalty_program_ids).__name__,
            repr(loyalty_program_ids)[:500],
        )
        if loyalty_program_ids in (None, False):
            session.oca_applied_loyalty_program_ids = False
            _logger.info(
                "OCA_PROMOS_SESSION: campo oca_applied_loyalty_program_ids limpiado (False/None)"
            )
            return True
        if isinstance(loyalty_program_ids, str):
            session.oca_applied_loyalty_program_ids = loyalty_program_ids.strip() or False
            _logger.info(
                "OCA_PROMOS_SESSION: guardado CSV desde str | session_id=%s | valor=%s",
                session.id,
                session.oca_applied_loyalty_program_ids,
            )
            return True
        try:
            ids = [
                int(x)
                for x in loyalty_program_ids
                if x is not None and str(x).strip() != ""
            ]
        except (TypeError, ValueError) as err:
            session.oca_applied_loyalty_program_ids = False
            _logger.warning(
                "OCA_PROMOS_SESSION: error parseando lista de IDs, se limpia campo | %s",
                err,
            )
            return True
        session.oca_applied_loyalty_program_ids = (
            ",".join(str(i) for i in ids) if ids else False
        )
        _logger.info(
            "OCA_PROMOS_SESSION: guardado desde lista | session_id=%s | ids=%s | csv=%s",
            session.id,
            ids,
            session.oca_applied_loyalty_program_ids,
        )
        return True
