# -*- coding: utf-8 -*-

from odoo import fields, models


class PosConfig(models.Model):
    """
    Configuración QZ Tray por punto de venta.

    Permite enviar HTML del ticket de cambio (y opcionalmente el recibo POS)
    a una impresora local vía QZ Tray sin usar el diálogo de impresión del navegador.
    """

    _inherit = "pos.config"

    # Bloque: activar integración QZ en este POS.
    use_qz_tray = fields.Boolean(
        string="Usar QZ Tray",
        help="Si está activo y se indica el nombre de impresora, el ticket de "
        "cambio (y el recibo POS si se marca) se envían por QZ Tray.",
    )
    # Bloque: nombre exacto de la cola de impresión según el SO / QZ Tray.
    qz_tray_printer_name = fields.Char(
        string="Nombre impresora QZ",
        help="Nombre exacto de la impresora (como aparece en QZ Tray o en "
        "Configuración de impresoras del sistema).",
    )
    # Bloque: usar QZ también para el botón Imprimir recibo de la pantalla de recibo.
    qz_tray_print_pos_receipt = fields.Boolean(
        string="Recibo POS también por QZ",
        help="Si está activo junto con QZ Tray, el recibo estándar del POS se "
        "renderiza a HTML y se manda por QZ en lugar del servicio de impresión del navegador.",
    )
