# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    default_partner_street = fields.Char(
        string="Default Partner Street",
        help="Valor por defecto para Calle al crear clientes desde el POS.",
    )
    default_partner_city = fields.Char(
        string="Default Partner City",
        help="Valor por defecto para Ciudad al crear clientes desde el POS.",
    )
