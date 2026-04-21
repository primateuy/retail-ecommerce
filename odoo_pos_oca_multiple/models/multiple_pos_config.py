import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class MultiplePosConfig(models.Model):
    _name = 'multiple.pos.config'
    _description = 'Terminal OCA POSLink (PosID / PinPad)'

    name = fields.Char('Alias')
    codigo_terminal = fields.Char('Código Terminal (PosID)')
    payment_provider_id = fields.Many2one(
        'payment.provider',
        string='Configurar multiples POS',
    )
