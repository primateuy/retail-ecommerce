# -*- coding: utf-8 -*-

from odoo import models, fields


class AccountJournal(models.Model):
    _inherit = "account.journal"

    internal_code = fields.Char(string="Código interno")
