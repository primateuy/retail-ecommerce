# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_res_partner(self):
        result = super()._loader_params_res_partner()
        fields = result.setdefault('search_params', {}).setdefault('fields', [])
        # category_id is not always loaded by default and is useful for domains like
        # [('category_id', 'in', [...])]
        for field_name in ['category_id']:
            if field_name not in fields:
                fields.append(field_name)
        return result
