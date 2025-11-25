# -*- coding: utf-8 -*-

from odoo import models, fields


class AccountPayment(models.Model):
    _inherit = "account.payment"

    id_fenicio = fields.Char('ID Pago')
    id_externo = fields.Char('ID Externo')
    codigo = fields.Char('Código del medio de pago.')
    conector = fields.Char('Conector')
    estado = fields.Char('Estado')
    fecha_vencimiento = fields.Datetime('Fecha Vencimiento')
    fecha_cancelacion = fields.Datetime('Fecha Cancelacion')
    cuotas = fields.Integer('Cuotas')
    bin = fields.Char('bin')
    autorizacion = fields.Char('Autorización')
