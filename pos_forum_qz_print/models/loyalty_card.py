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
        # 🔴 El guion NO viaja en el código de barras, a propósito.
        #
        # La lectora no "lee texto": teclea. Emite el scancode de cada carácter con
        # el layout con el que viene configurada —US— y la caja tiene un teclado
        # español/latinoamericano, donde esa tecla es el apóstrofe. Así,
        # "0445-2781-4ece" entra como "0445'2781'4ece" en cualquier campo del
        # sistema. Dentro del PDV lo arregla normalizeScannedCouponCode
        # (loyalty_code_scan.js), pero fuera de ahí —una búsqueda en el backend, un
        # bloc de notas— no lo arregla nadie.
        #
        # Codificando sólo los alfanuméricos el problema desaparece de raíz: no hay
        # ningún carácter cuyo scancode dependa del layout. El código legible que va
        # impreso abajo SÍ conserva los guiones, porque es el que el cajero teclea a
        # mano y el que figura en Odoo.
        valor_barcode = "".join(c for c in value if c.isalnum())
        # normalize=False: el código del cupón es un identificador exacto, no se le
        # puede recortar nada (a diferencia del "Order " de la referencia del pedido).
        info = self.env["ir.actions.report"]._forum_code128_thermal(valor_barcode, normalize=False)
        if not info:
            _logger.debug(
                "pos_forum_qz_print: barcode cupón no generado | card=%s | valor=%r",
                self.id,
                valor_barcode,
            )
        return info

    def get_pos_coupon_barcode_data_uri(self):
        """
        Compatibilidad: sólo el data URI del Code128 del cupón.
        """
        self.ensure_one()
        info = self.get_pos_coupon_barcode_info()
        return info["uri"] if info else False
