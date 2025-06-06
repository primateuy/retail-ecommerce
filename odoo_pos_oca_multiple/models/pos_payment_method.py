import threading
import pprint
import logging
import requests

from time import sleep
from odoo import fields, models, api, SUPERUSER_ID
from datetime import datetime

from odoo.addons.l10n_be_coda.models.account_journal import transaction_code

_logger = logging.getLogger("POS PAYMENT METHOD")


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_multiple = fields.Boolean('Tiene multiples POS')
    payment_provider = fields.Many2one(comodel_name='payment.provider', string="Proveedor de Pago Asociado")
    pos_id = fields.Many2one('multiple.pos.config', string='POS Asociado')

    @api.onchange('payment_provider', 'payment_provider.is_multiple')
    def _onchange_payment_provider(self):
        for rec in self:
            if rec.payment_provider:
                rec.url_webservice = rec.payment_provider.url_webservice
                rec.codigo_sistema = rec.payment_provider.codigo_sistema
                rec.client_app_id = rec.payment_provider.client_app_id
                rec.codigo_sucursal = rec.payment_provider.codigo_sucursal
                rec.is_multiple = rec.payment_provider.is_multiple

    @api.onchange('pos_id')
    def _onchange_pos_id(self):
        for rec in self:
            if rec.pos_id:
                rec.codigo_terminal = rec.pos_id.codigo_terminal