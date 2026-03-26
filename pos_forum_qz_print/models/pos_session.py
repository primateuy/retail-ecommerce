# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    """
    Extiende la carga de datos del POS para incluir flags y nombre de impresora QZ.
    """

    _inherit = "pos.session"

    def _get_pos_ui_pos_config(self, params):
        """
        Asegura que la configuración enviada al frontend incluya los campos QZ.

        Se fusionan explícitamente por si la lista de campos del loader no los trae.
        """
        # Bloque: datos estándar del TPV (incluye campos de odoo_pos_oca, etc.).
        config = super()._get_pos_ui_pos_config(params)
        # Bloque: lectura directa para no depender de search_read(fields=...).
        cfg = self.env["pos.config"].sudo().browse(config["id"])
        config["use_qz_tray"] = cfg.use_qz_tray
        config["qz_tray_printer_name"] = cfg.qz_tray_printer_name or ""
        config["qz_tray_print_pos_receipt"] = cfg.qz_tray_print_pos_receipt
        # Bloque: solo en debug para no llenar logs en cada apertura de sesión.
        if cfg.use_qz_tray:
            _logger.debug(
                "pos_forum_qz_print: POS config cargada con QZ activo | config_id=%s | "
                "impresora=%r | recibo_pos_por_qz=%s",
                cfg.id,
                config["qz_tray_printer_name"],
                cfg.qz_tray_print_pos_receipt,
            )
        return config
