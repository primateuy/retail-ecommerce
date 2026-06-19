# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
import logging;

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def create_payment_fenicio(self, json_data_pago, mode_update=False, payment_ids=False):
        self.ensure_one()

        fenicio_compania = self.env.company

        if mode_update:
            payment_ids.write({'estado': json_data_pago['estado']})
            if json_data_pago['estado'] == 'CANCELADO':
                payment_ids.action_draft()
                payment_ids.cancel()
            return False

        # El diario de pago se toma de la configuración del sitio Fenicio
        # (Diario de Pago Fenicio). Si no está configurado, se usa el diario
        # Fenicio por defecto (feni). No se usa el diario de la venta, que puede
        # tener documentos fiscales activados y rompe el registro de pago.
        journal_id = False
        sale_order = self.line_ids.sale_line_ids.order_id[:1]
        if sale_order and sale_order.website_id.fenicio_payment_journal_id:
            journal_id = sale_order.website_id.fenicio_payment_journal_id
        if not journal_id:
            journal_id = self.env['account.journal'].search([
                ('code', '=', 'feni'),
                ('company_id', '=', fenicio_compania.id)
            ], limit=1)
        if not journal_id:
            raise UserError(
                'No se configuró un Diario de Pago Fenicio en el sitio web '
                'ni se encontró el diario por defecto (feni).'
            )

        payment_method_line = journal_id.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            # Agregar automáticamente el método Manual si el diario no tiene ninguno configurado
            manual_method = self.env['account.payment.method'].search([
                ('code', '=', 'manual'),
                ('payment_type', '=', 'inbound'),
            ], limit=1)
            if manual_method:
                payment_method_line = self.env['account.payment.method.line'].create({
                    'name': manual_method.name,
                    'payment_method_id': manual_method.id,
                    'journal_id': journal_id.id,
                })
            else:
                raise UserError('El diario %s no tiene configurado un método de pago inbound' % journal_id.name)

        payment_register_id = self.env['account.payment.register'].with_context(active_ids=self.ids, active_model='account.move', active_id=self.id).create({
            'journal_id': journal_id.id,
            'payment_date': json_data_pago['fechaPago'],
            'payment_method_line_id': payment_method_line.id,
            'company_id': fenicio_compania.id,
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
                'company_id': fenicio_compania.id,
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
            'company_id': self.env.company.id,
        })
        move_reversal_id.reverse_moves()

