# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    pos_receipt_logo = fields.Binary(
        string='Logo de Rutina de Impresión',
        attachment=True,
        help='Logo que se mostrará en el encabezado del ticket del POS. '
             'Si no se configura, se usará el logo general de la empresa.',
    )
