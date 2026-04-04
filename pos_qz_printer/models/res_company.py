# -*- coding: utf-8 -*-

from odoo import fields, models


class Company(models.Model):
    _inherit = "res.company"

    pos_printer = fields.Char(string="POS Printer", help="Set Name Of Printer From Where You Want To Print Receipt.")
