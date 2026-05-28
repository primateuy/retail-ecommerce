# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    envio_cfc_online = fields.Boolean(
        string="Envío CFC online",
        default=False,
        help="Si está activo, al confirmar la orden Odoo intenta firmar el "
             "CFC con UCFE en el momento. Si está inactivo (modo batch, por "
             "defecto), la factura queda pendiente y el cron de "
             "l10n_uy_cfc_efac la envía en su próxima corrida (cada 15 min). "
             "En ambos casos la operativa del cajero NO se interrumpe si "
             "UCFE no está disponible.",
    )
