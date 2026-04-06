# -*- coding: utf-8 -*-
"""
Modelo para extender pos.config con campo de configuración para descargar factura
"""

from odoo import models, fields


class PosConfig(models.Model):
    """
    Extensión del modelo pos.config para agregar configuración
    de descarga de factura
    """
    _inherit = 'pos.config'

    pos_points_policy = fields.Text(
        string='Sistema de puntos',
        help='Texto a mostrar en el recibo del POS con la política o sistema '
             'de puntos vigente.'
    )
    receipt_logo = fields.Binary(
        related='company_id.pos_receipt_logo',
        readonly=False,
        string='Logo de Rutina de Impresión',
    )
    download_invoice = fields.Boolean(
        string='Descargar factura',
        default=False,
        help='Si está marcado, se mantendrá el comportamiento estándar de Odoo '
             'para descargar la factura en el POS. Si está desmarcado (por defecto), '
             'no se descargará la factura automáticamente.'
    )

