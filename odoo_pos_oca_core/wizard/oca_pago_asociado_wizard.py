# -*- coding: utf-8 -*-
"""Diálogo «Crear pago asociado» de la transacción OCA."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OcaPagoAsociadoWizard(models.TransientModel):
    _name = 'oca.pago.asociado.wizard'
    _description = 'Crear el pago contable de un cobro OCA'

    transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Cobro',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Cliente',
        required=True,
        ondelete='cascade',
    )
    date = fields.Date(string='Fecha del pago', required=True)
    amount = fields.Monetary(related='transaction_id.amount', string='Monto')
    currency_id = fields.Many2one(related='transaction_id.currency_id')
    journal_id = fields.Many2one(related='transaction_id.provider_id.journal_id', string='Diario')
    pos_id = fields.Char(related='transaction_id.pos_id', string='Terminal')
    ticket_number = fields.Char(related='transaction_id.ticket_number', string='Ticket')
    authorization_code = fields.Char(related='transaction_id.authorization_code', string='Autorización')
    advertencias = fields.Text(string='Advertencias', compute='_compute_advertencias')
    acepto_advertencias = fields.Boolean(
        string='Entiendo que el cobro puede quedar dos veces y quiero crear el pago igual',
    )

    def _valores_del_cobro(self, tx):
        """Cliente y fecha precargados: los del cobro (la fecha, en la hora local)."""
        momento = tx.create_date
        return {
            'partner_id': tx.partner_id.id,
            'date': fields.Date.context_today(self, timestamp=momento) if momento
            else fields.Date.context_today(self),
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get('transaction_id'):
            tx = self.env['payment.transaction'].browse(res['transaction_id'])
            for campo, valor in self._valores_del_cobro(tx).items():
                if campo in fields_list and not res.get(campo):
                    res[campo] = valor
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('transaction_id'):
                tx = self.env['payment.transaction'].browse(vals['transaction_id'])
                for campo, valor in self._valores_del_cobro(tx).items():
                    vals.setdefault(campo, valor)
        return super().create(vals_list)

    @api.depends('transaction_id')
    def _compute_advertencias(self):
        for wizard in self:
            lista = (
                wizard.transaction_id._oca_advertencias_pago_asociado() if wizard.transaction_id else []
            )
            wizard.advertencias = '\n'.join(lista)

    def action_confirmar(self):
        self.ensure_one()
        if self.advertencias and not self.acepto_advertencias:
            raise UserError(_('Marcá que entendés las advertencias para crear el pago igual.'))
        pago = self.transaction_id._oca_crear_pago_asociado(
            self.partner_id, self.date, aceptar_advertencias=self.acepto_advertencias,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pago'),
            'res_model': 'account.payment',
            'res_id': pago.id,
            'view_mode': 'form',
            'target': 'current',
        }
