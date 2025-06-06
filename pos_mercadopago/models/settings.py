from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mp_qr_type = fields.Selection([
        ('static', 'Fixed QR/Model attended'),
        ('dynamic', 'Dynamic QR/Dynamic Model')
    ], string="QR Type", default='static', config_parameter='pos_mercadopago.mp_qr_type')

    def get_qr_conf(self):
        return self.mp_qr_type