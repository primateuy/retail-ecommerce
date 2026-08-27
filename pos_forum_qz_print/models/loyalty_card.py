# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class LoyaltyCard(models.Model):
    """
    Soporte de impresión POS: barcode embebido para QWeb/HTML en QZ (sin depender de /report/barcode/).
    """

    _inherit = "loyalty.card"

    def get_pos_coupon_barcode_info(self):
        """
        Code128 del código del cupón, listo para el ticket térmico de 80 mm.

        El reporte estándar usa ``t-field`` con widget barcode; en QZ suele fallar la
        ruta HTTP. Se delega en ``ir.actions.report._forum_code128_thermal``
        (odoo_pos_oca), que genera el PNG alineado a módulo y devuelve el tamaño
        físico en mm con el que hay que pintarlo.

        :return: dict con ``uri``/``width_mm``/``height_mm``/``value``, o ``False``.
        """
        self.ensure_one()
        value = (self.code or "").strip()
        if not value:
            return False
        # normalize=False: el código del cupón es un identificador exacto, no se le
        # puede recortar nada (a diferencia del "Order " de la referencia del pedido).
        info = self.env["ir.actions.report"]._forum_code128_thermal(value, normalize=False)
        if not info:
            _logger.debug(
                "pos_forum_qz_print: barcode cupón no generado | card=%s | valor=%r",
                self.id,
                value,
            )
        return info

    def get_pos_coupon_barcode_data_uri(self):
        """
        Compatibilidad: sólo el data URI del Code128 del cupón.
        """
        self.ensure_one()
        info = self.get_pos_coupon_barcode_info()
        return info["uri"] if info else False
