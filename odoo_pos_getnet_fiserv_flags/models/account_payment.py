# -*- coding: utf-8 -*-
"""Suma las condiciones Getnet a los flags unificados de POS integrado."""

from odoo import api, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.onchange('journal_id', 'payment_method_line_id')
    def _onchange_getnet_limpia_check_fiserv(self):
        """
        Un pago de Getnet no puede quedar marcado «Cobrar en terminal Fiserv».

        El onchange de Fiserv marca su check al elegir un diario Fiserv (el
        form de pagos abre en uno por defecto) pero NO lo desmarca al pasar
        a otro diario. En una BD con ambos adquirentes ese check se queda
        pegado en pagos Getnet, y como la vista de Fiserv repite sus
        condiciones además del flag compartido —(fiserv_charge_on_pos and
        not fiserv_tx_is_done)— el botón Confirmar quedaba oculto para
        siempre, incluso con el cobro Getnet ya aprobado en el pinpad.

        Limpiar el flag compartido no alcanza: hay que limpiar el dato.
        """
        for pay in self:
            if pay.getnet_is_getnet_payment_line and pay.fiserv_charge_on_pos:
                pay.fiserv_charge_on_pos = False
                pay.fiserv_terminal_id = False

    def _getnet_limpiar_check_fiserv(self):
        """Misma limpieza fuera del form (RPC, importaciones, wizard)."""
        pegados = self.filtered(
            lambda p: p.getnet_is_getnet_payment_line and p.fiserv_charge_on_pos)
        if pegados:
            pegados.write({
                'fiserv_charge_on_pos': False,
                'fiserv_terminal_id': False,
            })
        return pegados

    def action_getnet_create_transaction(self):
        """Antes de cobrar por Getnet, ningún check de Fiserv puede quedar."""
        self._getnet_limpiar_check_fiserv()
        return super().action_getnet_create_transaction()

    @api.depends('getnet_post_blocked', 'getnet_cancel_blocked',
                 'getnet_draft_blocked', 'getnet_is_getnet_payment_line')
    def _compute_pos_integrated_flags(self):
        """Suma los bloqueos Getnet a los flags compartidos con Fiserv.

        La condición NO se replica acá: vive en
        ``_compute_getnet_button_guards`` (odoo_pos_getnet_backend), que es
        lo que usa Getnet standalone. Este puente solo hace el merge.
        """
        super()._compute_pos_integrated_flags()
        for pay in self:
            if pay.getnet_is_getnet_payment_line:
                # El pago es de Getnet: los términos Fiserv NO aplican y no
                # pueden bloquearlo. Un pago tiene una sola línea de método
                # de pago, y el flujo Fiserv exige la suya para arrancar.
                #
                # Hace falta ignorarlos, no solo sumar los nuestros, porque
                # fiserv_charge_on_pos se queda pegado: el onchange de
                # Fiserv lo marca al elegir un diario Fiserv (el form de
                # pagos abre en uno por defecto) y no lo desmarca al
                # cambiar de diario. Con el check pegado su condición
                # (charge_on_pos and not fiserv_tx_is_done) nunca se apaga
                # en un pago Getnet, y Confirmar quedaba oculto para
                # siempre aun con el cobro aprobado en el pinpad.
                pay.pos_integrated_post_blocked = pay.getnet_post_blocked
                pay.pos_integrated_cancel_blocked = pay.getnet_cancel_blocked
                pay.pos_integrated_draft_blocked = pay.getnet_draft_blocked
                continue
            pay.pos_integrated_post_blocked = (
                pay.pos_integrated_post_blocked or pay.getnet_post_blocked)
            pay.pos_integrated_cancel_blocked = (
                pay.pos_integrated_cancel_blocked or pay.getnet_cancel_blocked)
            pay.pos_integrated_draft_blocked = (
                pay.pos_integrated_draft_blocked or pay.getnet_draft_blocked)
