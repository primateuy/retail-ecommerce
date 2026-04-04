# -*- coding: utf-8 -*-
"""
Extiende payment.provider con el código Fiserv ITD y credenciales compartidas.

Los campos de conexión (URL, SystemId, Branch) se pueden copiar al método de
pago POS mediante onchange; con múltiples POS, el PosID viene de fiserv.pos.terminal.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    """
    Añade proveedor Fiserv ITD y parámetros de homologación multi-terminal.
    """

    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('fiserv', 'Fiserv ITD')],
        ondelete={'fiserv': 'set default'},
    )
    fiserv_is_multiple = fields.Boolean(
        string='Fiserv: múltiples POS',
        help='Si está activo, en el método de pago POS se elige un terminal de la lista.',
    )
    fiserv_url_webservice = fields.Char(
        string='Fiserv URL ITD',
        help='URL base del servicio ITD sin barra final (ej. https://testitd.firstdata.com/v2/ITDService).',
    )
    fiserv_system_id = fields.Char(
        string='SystemId',
        help='Identificador único asignado por Fiserv al comercio (ITD).',
    )
    fiserv_branch = fields.Char(
        string='Branch',
        help='Identificador de sucursal ITD (texto, hasta 100 caracteres).',
    )
    fiserv_client_app_id = fields.Char(
        string='ClientAppId',
        default='1',
        help='Identificador de caja / aplicación cliente en ITD.',
    )
    fiserv_terminal_ids = fields.One2many(
        comodel_name='fiserv.pos.terminal',
        inverse_name='payment_provider_id',
        string='Terminales (PosID)',
    )
