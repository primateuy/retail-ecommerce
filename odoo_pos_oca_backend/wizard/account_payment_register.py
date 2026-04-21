# -*- coding: utf-8 -*-
"""
Extensión del wizard de registro de pago para soporte de terminal OCA POSLink.

Permite al usuario marcar «Cobrar en terminal» directamente desde el popup
de Registrar pago de una factura. Los valores se propagan al account.payment
creado y el action_post() existente se encarga del envío al pinpad.
"""

from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    """Agrega campos OCA al wizard de registro de pago de facturas."""

    _inherit = "account.payment.register"

    oca_charge_on_pos = fields.Boolean(
        string="Cobrar en terminal OCA (ITD)",
        default=False,
        help="Si está marcado, al crear el pago se enviará la operación al pinpad.",
    )
    oca_is_oca_journal = fields.Boolean(
        string="Diario OCA (técnico)",
        compute="_compute_oca_is_oca_journal",
        help="True cuando el diario seleccionado tiene proveedor OCA en su línea de método de pago.",
    )
    oca_multiple_pos_id = fields.Many2one(
        comodel_name="multiple.pos.config",
        string="Terminal OCA (PosID)",
        domain="[('id', 'in', oca_selectable_pos_ids)]",
        help="Terminal PosID a usar para el cobro.",
    )
    oca_selectable_pos_ids = fields.Many2many(
        comodel_name="multiple.pos.config",
        compute="_compute_oca_terminal_fields",
        string="Terminales disponibles (técnico)",
    )
    oca_need_pos_choice = fields.Boolean(
        string="Requiere elegir terminal (técnico)",
        compute="_compute_oca_terminal_fields",
    )

    @api.depends("journal_id", "payment_method_line_id")
    def _compute_oca_is_oca_journal(self):
        """Detecta si la línea de método de pago pertenece a un proveedor OCA."""
        for wizard in self:
            provider = wizard.payment_method_line_id.payment_provider_id
            wizard.oca_is_oca_journal = bool(provider and provider.code == "oca")

    @api.depends("journal_id", "payment_method_line_id")
    def _compute_oca_terminal_fields(self):
        """Lista los terminales del proveedor OCA del método de pago."""
        for wizard in self:
            wizard.oca_selectable_pos_ids = False
            wizard.oca_need_pos_choice = False
            provider = wizard.payment_method_line_id.payment_provider_id
            if not provider or provider.code != "oca":
                continue
            terminals = self.env["multiple.pos.config"].search(
                [("payment_provider_id", "=", provider.id)]
            )
            wizard.oca_selectable_pos_ids = terminals
            wizard.oca_need_pos_choice = len(terminals) > 0

    @api.onchange("oca_charge_on_pos")
    def _onchange_oca_charge_on_pos(self):
        """Limpia terminal al desmarcar; preselecciona si hay un solo terminal."""
        if not self.oca_charge_on_pos:
            self.oca_multiple_pos_id = False
            return
        terminals = self.oca_selectable_pos_ids
        if len(terminals) == 1:
            self.oca_multiple_pos_id = terminals[0]

    def _oca_get_invoice_ids_from_batch(self, batch_result):
        """Obtiene los IDs de facturas asociadas al lote de líneas a reconciliar."""
        lines = batch_result.get("lines", self.env["account.move.line"])
        invoices = lines.mapped("move_id").filtered(
            lambda m: m.is_invoice(include_receipts=True)
        )
        return invoices.ids

    def _create_payment_vals_from_wizard(self, batch_result):
        """Inyecta valores OCA en el account.payment creado desde el wizard."""
        vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.oca_charge_on_pos:
            vals["oca_charge_on_pos"] = True
            if self.oca_multiple_pos_id:
                vals["oca_multiple_pos_id"] = self.oca_multiple_pos_id.id
            vals["oca_source_invoice_ids"] = [
                (6, 0, self._oca_get_invoice_ids_from_batch(batch_result))
            ]
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        """Inyecta valores OCA en el account.payment creado por lote."""
        vals = super()._create_payment_vals_from_batch(batch_result)
        if self.oca_charge_on_pos:
            vals["oca_charge_on_pos"] = True
            if self.oca_multiple_pos_id:
                vals["oca_multiple_pos_id"] = self.oca_multiple_pos_id.id
            vals["oca_source_invoice_ids"] = [
                (6, 0, self._oca_get_invoice_ids_from_batch(batch_result))
            ]
        return vals
