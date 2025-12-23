# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api, _

class AccountMove(models.Model):
    
    _inherit = 'account.move'

    bi_amount_in_currency = fields.Monetary(string="Amount in currency")


class PosPaymentMethod(models.Model):

    _inherit = "pos.payment.method"

    currency_id = fields.Many2one("res.currency", 'Currency',compute='_compute_currency')

    def _compute_currency(self):
        for pm in self:
            pm.currency_id = pm.company_id.currency_id.id
            if pm.journal_id and pm.journal_id.currency_id:
                pm.currency_id = pm.journal_id.currency_id.id