# -*- coding: utf-8 -*-
"""
Getnet y Fiserv en el mismo pago contable, sin pisarse.

Un pago tiene UNA línea de método. Esa línea dice de qué adquirente es el
pago, y los bloqueos del otro no pueden aplicarle aunque su check «cobrar en
terminal» haya quedado marcado (onchange viejo, RPC, importación, wizard).
"""

from odoo import api, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # ------------------------------------------------------------------
    # Bloqueos: manda la línea del pago
    # ------------------------------------------------------------------
    def _getnet_must_charge_on_terminal(self):
        """Un pago Fiserv no espera nada de la terminal Getnet."""
        self.ensure_one()
        if self.fiserv_is_fiserv_payment_line:
            return False
        return super()._getnet_must_charge_on_terminal()

    def _fiserv_must_charge_on_terminal(self):
        """Un pago Getnet no espera nada de la terminal Fiserv."""
        self.ensure_one()
        if self.getnet_is_getnet_payment_line:
            return False
        return super()._fiserv_must_charge_on_terminal()

    @api.depends('fiserv_is_fiserv_payment_line')
    def _compute_getnet_button_guards(self):
        """
        Los términos Getnet del form no bloquean un pago Fiserv. Se neutraliza
        sólo lo que viene de un check pegado: un cobro Getnet real (en curso o
        aprobado) del mismo pago sigue bloqueando, porque es plata movida.
        """
        super()._compute_getnet_button_guards()
        for pay in self:
            if pay.fiserv_is_fiserv_payment_line:
                pay.getnet_post_blocked = pay.getnet_async_terminal_pending

    @api.depends('getnet_is_getnet_payment_line')
    def _compute_pos_integrated_flags(self):
        """Los términos Fiserv del form no bloquean un pago Getnet (ídem)."""
        super()._compute_pos_integrated_flags()
        for pay in self:
            if pay.getnet_is_getnet_payment_line:
                pay.pos_integrated_post_blocked = (
                    pay.fiserv_async_terminal_pending or pay.fiserv_tx_is_pending)

    # ------------------------------------------------------------------
    # Checks pegados: se limpian antes de cobrar
    # ------------------------------------------------------------------
    @api.onchange('journal_id', 'payment_method_line_id')
    def _onchange_getnet_fiserv_limpia_checks(self):
        for pay in self:
            if pay.getnet_is_getnet_payment_line:
                pay.fiserv_charge_on_pos = False
                pay.fiserv_terminal_id = False
            if pay.fiserv_is_fiserv_payment_line:
                pay.getnet_charge_on_pos = False
                pay.getnet_terminal_id = False

    def action_getnet_create_transaction(self):
        """Antes de cobrar por Getnet, ningún check de Fiserv puede quedar."""
        pegados = self.filtered(lambda p: p.fiserv_charge_on_pos)
        if pegados:
            pegados.write({'fiserv_charge_on_pos': False, 'fiserv_terminal_id': False})
        return super().action_getnet_create_transaction()

    def action_fiserv_create_transaction(self):
        """Antes de cobrar por Fiserv, ningún check de Getnet puede quedar."""
        pegados = self.filtered(lambda p: p.getnet_charge_on_pos)
        if pegados:
            pegados.write({'getnet_charge_on_pos': False, 'getnet_terminal_id': False})
        return super().action_fiserv_create_transaction()
