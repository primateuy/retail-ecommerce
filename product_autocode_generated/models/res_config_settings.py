from odoo import fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_code_total_length_template = fields.Integer('Largo total del código de la plantilla', config_parameter='product_autocode_generated.total_length_template')
    product_code_total_length_variant = fields.Integer('Largo total del código de la variante', config_parameter='product_autocode_generated.total_length_variant')

    def action_configure_code_domains(self):
        return {
            'name': _('Configurar dominios de código'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.code.domain',
            'view_mode': 'tree,form',
            'context': {},
            'target': 'current',
        }
