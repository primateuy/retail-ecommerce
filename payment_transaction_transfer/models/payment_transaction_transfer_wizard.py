# -*- coding: utf-8 -*-
"""
Modelo transitorio (asistente) para crear transferencias internas desde
transacciones de pago (`payment.transaction`).

Se utiliza desde la acción del listado: agrupa las transacciones seleccionadas
por el diario contable configurado en el proveedor de pago y genera un
`account.payment` en modo transferencia interna por cada grupo.
"""

from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError


class PaymentTransactionTransferWizard(models.TransientModel):
    """
    Asistente de transferencia masiva desde transacciones de pago.

    Permite elegir un diario destino (liquidez) y, a partir de las
    transacciones seleccionadas en el listado, crear tantas transferencias
    internas como diarios de origen distintos existan entre los proveedores
    de dichas transacciones.
    """

    _name = "payment.transaction.transfer.wizard"
    _description = "Asistente: transferencia desde transacciones de pago"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        help="Compañía usada para filtrar diarios y validar coherencia con las transacciones.",
    )
    destination_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Diario destino",
        check_company=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help="Diario de liquidez donde se registrará el extremo destino de cada transferencia interna.",
    )

    def action_cancel(self):
        """
        Cierra el popup del asistente sin crear pagos ni modificar transacciones.

        Se usa desde el botón «Cancelar» en la vista formulario del transient.

        :return: dict: acción cliente que cierra la ventana modal.
        """
        # Bloque: cierre estándar de ventana emergente del backend.
        return {"type": "ir.actions.act_window_close"}

    def action_transfer(self):
        """
        Crea una transferencia interna por cada grupo de transacciones que
        comparten el mismo diario del proveedor de pago.

        Recorre `active_ids` del contexto, valida estado y datos, suma importes
        por diario origen y llama a `account.payment` + `action_post` para
        dejar los movimientos confirmados como en el flujo manual contable.

        :return: dict: ventana con los pagos generados o error de negocio.
        """
        self.ensure_one()

        # Bloque: validación del diario destino solo al transferir (no al cancelar).
        if not self.destination_journal_id:
            raise UserError(_("Indique el diario destino antes de transferir."))

        # Bloque: obtención de transacciones desde el listado que abrió el asistente.
        active_ids = self.env.context.get("active_ids") or []
        if not active_ids:
            raise UserError(
                _("Debe seleccionar al menos una transacción de pago en el listado.")
            )
        transactions = self.env["payment.transaction"].browse(active_ids).exists()
        if not transactions:
            raise UserError(_("No se encontraron transacciones válidas para procesar."))

        # Bloque: validación de compañía única (evita mezclar sociedades en un mismo lote).
        companies = transactions.mapped("company_id")
        if len(companies) > 1:
            raise UserError(
                _("Las transacciones seleccionadas pertenecen a más de una compañía; seleccione un solo conjunto homogéneo.")
            )
        if companies and companies != self.company_id:
            raise UserError(
                _("La compañía del asistente no coincide con la de las transacciones seleccionadas.")
            )

        # Bloque: el diario destino debe pertenecer a la misma compañía que las transacciones.
        if self.destination_journal_id.company_id != self.company_id:
            raise UserError(
                _("El diario destino debe pertenecer a la misma compañía que las transacciones.")
            )

        # Bloque: solo transacciones confirmadas contablemente (`done`); otros estados no suman para la transferencia.
        allowed_states = ("done",)
        invalid = transactions.filtered(lambda t: t.state not in allowed_states)
        if invalid:
            refs = ", ".join(invalid.mapped("reference")[:10])
            more = len(invalid) - 10
            suffix = _(" (y %s más…)") % more if more > 0 else ""
            raise UserError(
                _(
                    "Solo se pueden incluir transacciones en estado confirmado (realizado). "
                    "Revise: %(refs)s%(suffix)s"
                )
                % {"refs": refs, "suffix": suffix}
            )

        # Bloque: agrupación por diario de pago del proveedor (`account_payment` añade journal_id al proveedor).
        by_journal = defaultdict(lambda: self.env["payment.transaction"])
        missing_provider = self.env["payment.transaction"]
        missing_journal = self.env["payment.transaction"]

        for tx in transactions:
            # Sub-bloque: cada transacción debe tener proveedor y diario configurado en el proveedor.
            if not tx.provider_id:
                missing_provider |= tx
                continue
            journal = tx.provider_id.journal_id
            if not journal:
                missing_journal |= tx
                continue
            by_journal[journal] |= tx

        if missing_provider:
            raise UserError(
                _(
                    "Las siguientes transacciones no tienen proveedor de pago y no se pueden agrupar por diario: %s"
                )
                % ", ".join(missing_provider.mapped("reference")[:15])
            )
        if missing_journal:
            raise UserError(
                _(
                    "Configure el «Diario de pago» en el proveedor de estas transacciones: %s"
                )
                % ", ".join(missing_journal.mapped("reference")[:15])
            )

        # Bloque: creación de un pago por cada diario origen distinto.
        Payment = self.env["account.payment"]
        created = Payment.browse()

        for source_journal, tx_group in by_journal.items():
            # Sub-bloque: total del grupo y reglas básicas de negocio.
            total = sum(tx_group.mapped("amount"))
            if total <= 0:
                raise UserError(
                    _(
                        "El importe total del diario «%s» no es positivo; revise las transacciones seleccionadas."
                    )
                    % source_journal.display_name
                )
            if source_journal == self.destination_journal_id:
                raise UserError(
                    _(
                        "El diario origen «%s» coincide con el diario destino; elija otro destino o excluya ese grupo."
                    )
                    % source_journal.display_name
                )

            partner = source_journal.company_id.partner_id
            if not partner:
                raise UserError(
                    _("La compañía del diario «%s» no tiene contacto vinculado; esto es necesario para transferencias internas.")
                    % source_journal.display_name
                )

            # Sub-bloque: Odoo 17 calcula `is_internal_transfer` cuando partner = compañía del diario y hay diario destino.
            ref_label = _(
                "Transferencia desde transacciones de pago (%(count)s tx, diario %(journal)s)"
            ) % {
                "count": len(tx_group),
                "journal": source_journal.display_name,
            }
            payment_vals = {
                "payment_type": "outbound",
                "journal_id": source_journal.id,
                "destination_journal_id": self.destination_journal_id.id,
                "amount": total,
                "date": fields.Date.context_today(self),
                "partner_id": partner.id,
                "ref": ref_label[:255],
            }
            payment = Payment.create(payment_vals)
            # Sub-bloque: confirmar para generar el par de pagos y asientos como en la UI manual.
            payment.action_post()
            created |= payment

        # Bloque: resultado visible para el usuario (listado de pagos creados).
        return {
            "type": "ir.actions.act_window",
            "name": _("Transferencias internas creadas"),
            "res_model": "account.payment",
            "view_mode": "tree,form",
            "domain": [("id", "in", created.ids)],
            "context": {"create": False},
        }
