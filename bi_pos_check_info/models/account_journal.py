# -*- coding: utf-8 -*-

from odoo import api, fields, models , tools
import logging
_logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    allow_check_info = fields.Boolean(string="Allow Check Info")\

    @api.onchange('type')
    def _onchange_type(self):
        self.allow_check_info = False

