# -*- coding: utf-8 -*-
"""
Extiende pos.config con ticket de cambio y nota HTML (misma función que odoo_pos_oca).

Los campos llevan prefijo ``fiserv_`` para no colisionar con ``change_ticket_*`` de
``odoo_pos_oca`` si ambos módulos están instalados. La pantalla de recibo del POS
acepta cualquiera de los dos conjuntos de campos.
"""

from odoo import fields, models


class PosConfig(models.Model):
    """
    Configuración POS: reporte QWeb de ticket de cambio y texto opcional al pie.
    """

    _inherit = "pos.config"

    fiserv_change_ticket_report_id = fields.Many2one(
        comodel_name="ir.actions.report",
        string="Reporte ticket de cambio (Fiserv)",
        domain=[("model", "=", "pos.order")],
        help="PDF/HTML impreso desde el recibo POS (botones T-Cambio / Rutina). "
        "Por defecto puede usarse el reporte «Ticket de Cambio POS (Fiserv)» del módulo.",
    )
    fiserv_change_ticket_note = fields.Html(
        string="Texto final ticket de cambio (Fiserv)",
        help="Texto al pie del ticket de cambio (condiciones, plazos, etc.).",
    )
