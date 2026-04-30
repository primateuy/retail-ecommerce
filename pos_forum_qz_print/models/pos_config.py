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
    # Bloque: fallback de descarga cuando QZ no se puede conectar a la impresora.
    # Si está desactivado, ante un error de QZ se notifica sin descargar nada
    # (el usuario debe resolver la conexión manualmente).
    qz_tray_download_on_failure = fields.Boolean(
        string="Descargar reportes si QZ falla",
        default=False,
        help="Si está activo y la impresora QZ no responde durante la rutina de "
        "impresión, se descargan los reportes (recibo, ticket de cambio, voucher "
        "OCA y cupón de próxima compra cuando aplican) para que el operador los "
        "imprima manualmente. Si está desactivado, solo se notifica el error.",
    )
