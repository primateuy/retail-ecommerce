# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_receipt_logo = fields.Binary(
        related='company_id.pos_receipt_logo',
        readonly=False,
        string='Logo de Rutina de Impresión POS',
    )
