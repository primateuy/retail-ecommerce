# -*- coding: utf-8 -*-
"""Diálogo «Anular / Devolver en OCA» de la transacción."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OcaReversoWizard(models.TransientModel):
    _name = 'oca.reverso.wizard'
    _description = 'Anular / devolver un cobro OCA'

    transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Cobro',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    amount = fields.Monetary(related='transaction_id.amount', string='Monto')
    currency_id = fields.Many2one(related='transaction_id.currency_id')
    pos_id = fields.Char(related='transaction_id.pos_id', string='Terminal')
    ticket_number = fields.Char(related='transaction_id.ticket_number', string='Ticket')
    authorization_code = fields.Char(related='transaction_id.authorization_code', string='Autorización')
    card_last_four = fields.Char(related='transaction_id.card_last_four', string='Tarjeta')
    tx_date = fields.Datetime(related='transaction_id.create_date', string='Fecha del cobro')
    motivo = fields.Text(string='Motivo', required=True)
    advertencias = fields.Text(string='Advertencias', compute='_compute_advertencias')
    acepto_advertencias = fields.Boolean(
        string='Entiendo lo que queda descolgado y quiero anularlo igual',
    )

    @api.depends('transaction_id')
    def _compute_advertencias(self):
        for wizard in self:
            lista = wizard.transaction_id._oca_advertencias_reverso() if wizard.transaction_id else []
            wizard.advertencias = '\n'.join(lista)

    def action_confirmar(self):
        self.ensure_one()
        if self.advertencias and not self.acepto_advertencias:
            raise UserError(_('Marcá que entendés las advertencias para anular igual.'))
        resultado = self.transaction_id._oca_ejecutar_reverso(
            self.motivo, aceptar_advertencias=self.acepto_advertencias,
        )
        operacion = (
            _('la devolución') if resultado.get('operacion') == 'devolucion' else _('la anulación')
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'sticky': True,
                'title': _('Enviado a la terminal %s') % self.pos_id,
                'message': _(
                    'Se mandó %s del ticket %s. Seguí las indicaciones del pinpad; '
                    'cuando conteste te llega el aviso y queda registrada en la transacción.'
                ) % (operacion, self.ticket_number),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
