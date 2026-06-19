# -*- coding: utf-8 -*-

from odoo import fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    fenicio_numero_tarjeta = fields.Char(string='Número de Tarjeta')
    fenicio_terminacion_tarjeta = fields.Char(string='Terminación de Tarjeta')
    fenicio_bin = fields.Char(string='BIN')
    fenicio_titular_tarjeta = fields.Char(string='Titular de Tarjeta')
    fenicio_cuotas = fields.Integer(string='Cuotas')
    fenicio_banco = fields.Char(string='Banco')
    fenicio_autorizacion = fields.Char(string='Número de Autorización')
    fenicio_conector = fields.Char(string='Conector de Pago')
    fenicio_raw_pago = fields.Text(string='Datos de Pago (JSON)')

    # Sello / marca de la tarjeta (VISA, MASTER, etc.). Se reutiliza
    # deliberadamente el mismo nombre técnico que odoo_pos_oca_core para que
    # ambos módulos compartan la misma columna sin que Fenicio dependa de OCA.
    # El tipo (Char) debe coincidir con el de OCA core.
    issuer_name = fields.Char(
        string='Sello',
        help='Sello / marca de la tarjeta (VISA, MASTER, etc.).'
    )
