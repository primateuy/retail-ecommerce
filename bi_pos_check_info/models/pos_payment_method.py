# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    allow_check_info = fields.Boolean(related="journal_id.allow_check_info")
    




