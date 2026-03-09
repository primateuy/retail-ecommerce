# -*- coding: utf-8 -*-
from odoo import models


class LoyaltyRule(models.Model):
    _inherit = 'loyalty.rule'

    def _load_pos_data_fields(self, config_id):
        fields = list(super()._load_pos_data_fields(config_id))
        if 'customer_domain' not in fields:
            fields.append('customer_domain')
        return fields
