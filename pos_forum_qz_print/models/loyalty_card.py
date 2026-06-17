# -*- coding: utf-8 -*-

import base64
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class LoyaltyCard(models.Model):
    """
    Soporte de impresión POS: barcode embebido para QWeb/HTML en QZ (sin depender de /report/barcode/).
    """

    _inherit = "loyalty.card"

    def get_pos_coupon_barcode_data_uri(self):
        """
        PNG Code128 en data URI para el cupón térmico (QZ y PDF sin URL absoluta al barcode).

        El reporte estándar usa ``t-field`` con widget barcode; en QZ suele fallar la ruta HTTP.
        """
        self.ensure_one()
        value = (self.code or "").strip()
        if not value:
            return False
        try:
            # Mismos parámetros que el ticket de cambio (get_change_ticket_barcode_data_uri):
            # PNG ancho/alta resolución que luego se muestra a 400x80 px posicionado
            # absoluto sobre el ancho de página. Así sale igual de nítido.
            png = self.env["ir.actions.report"].barcode(
                "Code128", value, width=600, height=80
            )
        except Exception as err:
            _logger.debug(
                "pos_forum_qz_print: barcode cupón no generado | card=%s | %s",
                self.id,
                err,
            )
            return False
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
