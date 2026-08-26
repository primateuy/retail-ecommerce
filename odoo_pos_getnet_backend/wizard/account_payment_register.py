# -*- coding: utf-8 -*-
"""Wizard estándar de registro de pago con soporte de terminal Getnet."""

from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    getnet_charge_on_pos = fields.Boolean(
        string='Cobrar en terminal Getnet',
    )
    getnet_is_getnet_journal = fields.Boolean(
        compute='_compute_getnet_is_getnet_journal',
    )
    getnet_terminal_id = fields.Many2one(
        comodel_name='getnet.pos.terminal',
        string='Terminal Getnet',
    )
    getnet_selectable_terminal_ids = fields.Many2many(
        comodel_name='getnet.pos.terminal',
        compute='_compute_getnet_is_getnet_journal',
    )
    getnet_need_terminal_choice = fields.Boolean(
        compute='_compute_getnet_is_getnet_journal',
    )

    @api.depends('journal_id', 'payment_method_line_id')
    def _compute_getnet_is_getnet_journal(self):
        for wizard in self:
            provider = wizard.payment_method_line_id.payment_provider_id
            es_getnet = bool(provider and provider.code == 'getnet')
            wizard.getnet_is_getnet_journal = es_getnet
            terminals = provider.getnet_terminal_ids if es_getnet else \
                self.env['getnet.pos.terminal']
            wizard.getnet_selectable_terminal_ids = terminals
            wizard.getnet_need_terminal_choice = bool(
                es_getnet and provider.getnet_is_multiple
                and len(terminals) > 1)
            if es_getnet and not wizard.getnet_charge_on_pos:
                wizard.getnet_charge_on_pos = True
            if es_getnet and len(terminals) == 1:
                wizard.getnet_terminal_id = terminals

    def _getnet_payment_vals(self):
        """Valores Getnet a inyectar en el account.payment creado."""
        self.ensure_one()
        vals = {}
        if self.getnet_is_getnet_journal:
            vals.update({
                'getnet_charge_on_pos': self.getnet_charge_on_pos,
                'getnet_terminal_id': self.getnet_terminal_id.id,
                'getnet_source_invoice_ids': [(6, 0, self.line_ids.move_id.ids)],
            })
        return vals

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals.update(self._getnet_payment_vals())
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        vals = super()._create_payment_vals_from_batch(batch_result)
        vals.update(self._getnet_payment_vals())
        return vals
