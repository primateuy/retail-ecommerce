# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCountry(models.Model):
    _inherit = "res.country"

    pos_phone_length = fields.Integer(
        string="POS Phone Length",
        help="Cantidad exacta de digitos requerida para telefonos en POS.",
    )
    pos_phone_format = fields.Char(
        string="POS Phone Format",
        help="Formato esperado para telefonos en POS. Ejemplo: 09x xxx xxx",
    )
