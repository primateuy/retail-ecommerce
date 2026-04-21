import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    """
    Añade al proveedor OCA la opción de multi-POS y la lista de PosID. Los
    campos base de conexión (url_webservice, codigo_sistema, client_app_id,
    codigo_sucursal, branch) viven en ``odoo_pos_oca_core``.
    """

    _inherit = 'payment.provider'

    is_multiple = fields.Boolean(
        string='Tiene multiples POS',
        help='Si está activo, se configura una lista de terminales (PosID) '
        'y en el método de pago / account.payment se elige cuál enrutar.',
    )
    multiple_pos_ids = fields.One2many(
        'multiple.pos.config',
        'payment_provider_id',
        string='Configurar multiples POS',
    )
