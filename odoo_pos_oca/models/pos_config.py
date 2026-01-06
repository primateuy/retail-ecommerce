# -*- coding: utf-8 -*-
"""
Extensión del modelo pos.config para agregar configuración de ticket de cambio

Este módulo extiende pos.config para:
- Agregar campo para seleccionar el reporte de ticket de cambio
"""

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    """
    Extensión del modelo pos.config para ticket de cambio
    """
    _inherit = 'pos.config'

    # Campo para seleccionar el reporte de ticket de cambio
    # Este reporte se imprimirá cuando se haga clic en el botón "Ticket de cambio"
    change_ticket_report_id = fields.Many2one(
        'ir.actions.report',
        string='Reporte de Ticket de Cambio',
        domain=[('model', '=', 'pos.order')],
        help='Seleccione el reporte que se imprimirá cuando se haga clic en el botón "Ticket de cambio" en la pantalla de recibo.'
    )
