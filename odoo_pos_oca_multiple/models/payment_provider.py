import logging
from odoo import _, fields, models
_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    url_webservice = fields.Char('URL servicio web')
    codigo_sistema = fields.Char('Código Sistema (SystemId)')
    client_app_id = fields.Char('Client APP ID', default='1')
    codigo_sucursal = fields.Integer('Código Sucursal')
    is_multiple = fields.Boolean('Tiene multiples POS')
    multiple_pos_ids = fields.One2many('multiple.pos.config', 'payment_provider_id', string='Configurar multiples POS')

