# -*- coding: utf-8 -*-
"""
Extensión del wizard de registro de pago para soporte de terminal Fiserv ITD.

Permite al usuario marcar «Cobrar en terminal» directamente desde el popup
de Registrar pago de una factura. Los valores se propagan al account.payment
creado y el action_post() existente se encarga del envío al pinpad.
"""

from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    """Agrega campos Fiserv al wizard de registro de pago de facturas."""

    _inherit = "account.payment.register"

    fiserv_charge_on_pos = fields.Boolean(
        string="Cobrar en terminal Fiserv (ITD)",
        default=False,
        help="Si está marcado, al crear el pago se enviará la operación al pinpad.",
    )
    fiserv_is_fiserv_journal = fields.Boolean(
        string="Diario Fiserv (técnico)",
        compute="_compute_fiserv_is_fiserv_journal",
        help="True cuando el diario seleccionado tiene proveedor Fiserv en su línea de método de pago.",
    )
    fiserv_terminal_id = fields.Many2one(
        comodel_name="fiserv.pos.terminal",
        string="Terminal Fiserv (PosID)",
        domain="[('id', 'in', fiserv_selectable_terminal_ids)]",
        help="Terminal PosID a usar para el cobro.",
    )
    fiserv_selectable_terminal_ids = fields.Many2many(
        comodel_name="fiserv.pos.terminal",
        compute="_compute_fiserv_terminal_fields",
        string="Terminales disponibles (técnico)",
    )
    fiserv_need_terminal_choice = fields.Boolean(
        string="Requiere elegir terminal (técnico)",
        compute="_compute_fiserv_terminal_fields",
    )

    @api.depends("journal_id", "payment_method_line_id")
    def _compute_fiserv_is_fiserv_journal(self):
        """Detecta si la línea de método de pago pertenece a un proveedor Fiserv."""
        for wizard in self:
            provider = wizard.payment_method_line_id.payment_provider_id
            wizard.fiserv_is_fiserv_journal = bool(provider and provider.code == "fiserv")

    @api.depends("journal_id", "payment_method_line_id")
    def _compute_fiserv_terminal_fields(self):
        """Lista los terminales del proveedor Fiserv del método de pago."""
        for wizard in self:
            wizard.fiserv_selectable_terminal_ids = False
            wizard.fiserv_need_terminal_choice = False
            provider = wizard.payment_method_line_id.payment_provider_id
            if not provider or provider.code != "fiserv":
                continue
            terminals = self.env["fiserv.pos.terminal"].search(
                [("payment_provider_id", "=", provider.id)]
            )
            wizard.fiserv_selectable_terminal_ids = terminals
            wizard.fiserv_need_terminal_choice = len(terminals) > 0

    @api.onchange("fiserv_charge_on_pos")
    def _onchange_fiserv_charge_on_pos(self):
        """Limpia terminal al desmarcar; preselecciona si hay un solo terminal."""
        if not self.fiserv_charge_on_pos:
            self.fiserv_terminal_id = False
            return
        terminals = self.fiserv_selectable_terminal_ids
        if len(terminals) == 1:
            self.fiserv_terminal_id = terminals[0]

    def _fiserv_get_invoice_ids_from_batch(self, batch_result):
        """Obtiene los IDs de facturas asociadas al lote de líneas a reconciliar."""
        lines = batch_result.get("lines", self.env["account.move.line"])
        invoices = lines.mapped("move_id").filtered(
            lambda m: m.is_invoice(include_receipts=True)
        )
        return invoices.ids

    def _create_payment_vals_from_wizard(self, batch_result):
        """Inyecta valores Fiserv en el account.payment creado desde el wizard."""
        vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.fiserv_charge_on_pos:
            vals["fiserv_charge_on_pos"] = True
            if self.fiserv_terminal_id:
                vals["fiserv_terminal_id"] = self.fiserv_terminal_id.id
            vals["fiserv_source_invoice_ids"] = [
                (6, 0, self._fiserv_get_invoice_ids_from_batch(batch_result))
            ]
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        """Inyecta valores Fiserv en el account.payment creado por lote."""
        vals = super()._create_payment_vals_from_batch(batch_result)
        if self.fiserv_charge_on_pos:
            vals["fiserv_charge_on_pos"] = True
            if self.fiserv_terminal_id:
                vals["fiserv_terminal_id"] = self.fiserv_terminal_id.id
            vals["fiserv_source_invoice_ids"] = [
                (6, 0, self._fiserv_get_invoice_ids_from_batch(batch_result))
            ]
        return vals
