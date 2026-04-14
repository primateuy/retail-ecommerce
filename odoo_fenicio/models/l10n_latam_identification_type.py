# -*- coding: utf-8 -*-

from odoo import models, fields


class L10nLatamIdentificationType(models.Model):
    _inherit = 'l10n_latam.identification.type'

    codigo_fenicio = fields.Char(
        string='Código Fenicio',
        help='Código utilizado por Fenicio para identificar este tipo de documento (ej: CI_UY, RUC_UY)',
    )