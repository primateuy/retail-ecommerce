from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].append('codigo_sistema')
        result['search_params']['fields'].append('codigo_terminal')
        result['search_params']['fields'].append('client_app_id')
        result['search_params']['fields'].append('codigo_sucursal')
        return result
