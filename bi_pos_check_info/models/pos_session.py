# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].append('allow_check_info')
        return result

    def _get_pos_ui_pos_res_banks(self, params):
        banks = self.env['res.bank'].search_read(**params['search_params'])
        return banks

    def load_pos_data(self):
        loaded_data = {}
        self = self.with_context(loaded_data=loaded_data)
        for model in self._pos_ui_models_to_load():
            loaded_data[model] = self._load_model(model)
        self._pos_data_process(loaded_data)
        bank_data = self._get_pos_ui_pos_res_banks(self._loader_params_pos_res_banks())
        loaded_data['banks'] = bank_data
        return loaded_data

    def _loader_params_pos_res_banks(self):
        return {
            'search_params': {
                'domain': [],
                'fields': [],
            },
        }
