# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    refund_days_limit = fields.Integer(
        string="Refund Days Limit",
        help="Cantidad máxima de días desde la venta para permitir devoluciones. "
        "Si es 0, no se aplica límite.",
        default=0,
    )
