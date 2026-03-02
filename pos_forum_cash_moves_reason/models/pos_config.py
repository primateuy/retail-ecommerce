# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    cash_move_reason_ids = fields.Many2many(
        comodel_name="pos.move.reason",
        string="Cash Move Reasons",
        domain="[('company_id', '=', company_id)]",
        help="Razones habilitadas para entradas y salidas de efectivo en el POS.",
    )
