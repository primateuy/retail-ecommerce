# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2016-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#   See LICENSE file for full copyright and licensing details.
#   License URL : <https://store.webkul.com/license.html/>
#
#################################################################################
from odoo import models
from itertools import groupby
from odoo.osv.expression import AND

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _pos_ui_models_to_load(self):
        result = super()._pos_ui_models_to_load()
        if 'mongo.server.config' not in result:
            result.append('mongo.server.config')
        return result

    def _loader_params_mongo_server_config(self):
        return {
            'search_params': {
                'domain': [],
                'fields': ['cache_last_update_time', 'pos_live_sync', 'active_record'],
            },
        }

    def _get_pos_ui_mongo_server_config(self, params):
        return self.env['mongo.server.config'].with_context(sync_from_mongo= True).search_read(**params['search_params'])