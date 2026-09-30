# -*- coding: utf-8 -*-
"""
Wizard estándar «Registrar pago» frente a un método Fiserv.

El wizard crea el pago y lo CONFIRMA en el mismo paso; un cobro Fiserv tiene
que pasar antes por el pinpad. En 17.0 el wizard ofrecía «Cobrar en terminal»
y el pago terminaba rechazado por el guard de Confirmar con un mensaje que no
explicaba el camino. Ahora el wizard lo dice de entrada y no deja seguir: el
camino es «Pagar» en la factura (o «Registrar pago (con terminal)» en la
lista), que abre el form del pago.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    fiserv_is_fiserv_journal = fields.Boolean(
        string="Método Fiserv (técnico)",
        compute="_compute_fiserv_is_fiserv_journal",
    )

    @api.depends("journal_id", "payment_method_line_id")
    def _compute_fiserv_is_fiserv_journal(self):
        for wizard in self:
            # sudo: payment.provider es de Ajustes; se lee sólo 'code'.
            provider = wizard.payment_method_line_id.payment_provider_id.sudo()
            wizard.fiserv_is_fiserv_journal = bool(provider and provider.code == "fiserv")

    def action_create_payments(self):
        if any(wizard.fiserv_is_fiserv_journal for wizard in self):
            raise UserError(_(
                "El método de pago elegido cobra en la terminal Fiserv y este "
                "asistente confirma el pago sin pasar por el pinpad. Use «Pagar» "
                "en la factura (o «Registrar pago (con terminal)» en la lista): "
                "abre el pago con la factura cargada y el botón «Crear transacción»."))
        return super().action_create_payments()
