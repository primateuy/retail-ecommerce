# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def create_payment_fenicio(self, json_data_pago, mode_update=False, payment_ids=False):
        self.ensure_one()

        if mode_update:
            payment_ids.write({'estado': json_data_pago['estado']})
            if json_data_pago['estado'] == 'CANCELADO':
                payment_ids.action_draft()
                payment_ids.cancel()
            return False

        journal_id = self.env['account.journal'].search([('internal_code', '=', json_data_pago['codigo'])], limit=1)
        if not journal_id:
            raise UserError('No se encontró diario para registrar el pago')

        payment_register_id = self.env['account.payment.register'].with_context(active_ids=self.ids, active_model='account.move', active_id=self.id).create({
            'journal_id': journal_id.id,
            'payment_date': json_data_pago['fechaPago'],
        })
        payment_ids = payment_register_id._create_payments()
        if payment_ids:
            vals = {
                'id_fenicio': json_data_pago['id'],
                'id_externo': json_data_pago['idExterno'],
                'codigo': json_data_pago['codigo'],
                'conector': json_data_pago['conector'],
                'estado': json_data_pago['estado'],
                'fecha_vencimiento': self.env['api.internal'].change_date(json_data_pago['fechaVencimiento']),
                'fecha_cancelacion': self.env['api.internal'].change_date(json_data_pago['fechaCancelacion']),
                'cuotas': json_data_pago['cuotas'],
                'bin': json_data_pago['bin'],
                'autorizacion': json_data_pago['autorizacion'],
            }
            payment_ids.write(vals)

        if json_data_pago['estado'] == 'CANCELADO':
            payment_ids.action_draft()
            payment_ids.cancel()

        return payment_ids

    def crear_nota_credito(self):
        move_reversal_id = self.env['account.move.reversal'].create({
            'date_mode': 'entry',
            'reason': 'ORDEN CANCELADA DESDE FENICIO',
            'refund_method': 'cancel',
            'move_ids': [(6, 0, self.ids)],
        })
        move_reversal_id.reverse_moves()

