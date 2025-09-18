from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_code_total_length = fields.Integer('Largo total del código', config_parameter='product_auto_code_v2.total_length')

    def action_configure_code_domains(self):
        return {
            'name': _('Configurar dominios de código'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.code.domain',
            'view_mode': 'tree,form',
            'context': {},
            'target': 'current',
        }
