# -*- coding: utf-8 -*-

from odoo import api, fields, models , tools
import logging
_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    check_number = fields.Char()
    check_bank_account = fields.Char(string="Account No")
    check_owner = fields.Char(string="Customer")
    bank_id = fields.Many2one('res.bank',string="Bank Name")


