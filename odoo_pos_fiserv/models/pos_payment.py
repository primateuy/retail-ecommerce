# -*- coding: utf-8 -*-
"""
Extensión Fiserv sobre pos.payment: asociación con transacciones y helpers ITD.

Los campos invoice_number, payment_transaction_id, etc. no se declaran aquí:
- Con odoo_pos_oca instalado: los define ese módulo en pos.payment / account.payment.
- Solo Fiserv: instale odoo_pos_fiserv_pos_payment (mismos campos y vistas, sin duplicar con OCA).
"""

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    """
    Lógica específica del terminal Fiserv ITD.
    """

    _inherit = "pos.payment"

    def _fiserv_require_itd_pos_payment_fields(self):
        """
        Comprueba que existan los campos ITD en pos.payment (definidos por OCA o por el puente).

        No se declaran en odoo_pos_fiserv para no duplicarlos si odoo_pos_oca ya está instalado.
        """
        if "invoice_number" not in self.env["pos.payment"]._fields:
            raise UserError(
                _(
                    "Faltan campos ITD en Cobros TPV.\n\n"
                    "• Si no usa odoo_pos_oca: instale «odoo_pos_fiserv_pos_payment» (junto con Fiserv).\n"
                    "• Si usa odoo_pos_oca: debe estar instalado y actualizado (define esos campos); "
                    "no instale el puente anterior (duplicaría campos)."
                )
            )

    @api.model
    def create(self, vals):
        """
        Tras crear el registro (OCA / puente Fiserv u otra extensión que añada campos ITD),
        asocia transacciones Fiserv huérfanas si el método de pago es Fiserv.
        """
        payment = super().create(vals)
        if payment.payment_method_id.use_payment_terminal == "fiserv":
            payment._fiserv_require_itd_pos_payment_fields()
            payment._associate_fiserv_transaction()
        return payment

    def get_fiserv_invoice_number(self):
        """
        Obtiene el número de factura para enviar al POS Fiserv.

        Returns:
            str: Número de factura formateado para Fiserv
        """
        self.ensure_one()

        if self.invoice_number:
            return str(self.invoice_number)
        if self.pos_order_id:
            return str(self.pos_order_id.name)
        return str(self.id)

    def prepare_fiserv_data(self):
        """
        Prepara los datos para enviar al POS Fiserv.

        Returns:
            dict: Datos formateados para Fiserv
        """
        self.ensure_one()

        payment_method = self.payment_method_id

        if not payment_method or payment_method.use_payment_terminal != "fiserv":
            return {}

        self._fiserv_require_itd_pos_payment_fields()

        branch = payment_method.fiserv_branch or ""
        if not branch and payment_method.codigo_sucursal is not None:
            branch = str(payment_method.codigo_sucursal)
        return {
            "PosID": payment_method.codigo_terminal,
            "SystemId": payment_method.codigo_sistema,
            "Branch": branch,
            "ClientAppId": payment_method.client_app_id,
            "UserId": self.env.user.id,
            "Amount": self.amount,
            "Currency": self.currency_id.name,
            "Installments": self.installments,
            "InvoiceNumber": self.get_fiserv_invoice_number(),
            "TransactionDateTimeyyyyMMddHHmmssSSS": payment_method.get_formatted_timestamp(),
        }

    def _associate_fiserv_transaction(self):
        """
        Asocia transacciones Fiserv huérfanas con este pago.
        """
        try:
            payment_name = getattr(self, "name", "Unknown") or "Unknown"
            payment_amount = getattr(self, "amount", 0.0)

            _logger.info(
                "Buscando transacciones Fiserv para asociar con pago: %s (Monto: %s)",
                payment_name,
                payment_amount,
            )

            fiserv_provider = self.env["payment.provider"].sudo().search(
                [("code", "=", "fiserv")], limit=1
            )
            domain = [
                ("fiserv_transaction_id", "!=", False),
                ("pos_payment_id", "=", False),
                ("state", "in", ["pending", "done"]),
            ]
            if fiserv_provider:
                domain.append(("provider_id", "=", fiserv_provider.id))
            orphaned_transactions = self.env["payment.transaction"].sudo().search(domain)

            if not orphaned_transactions:
                _logger.info("No se encontraron transacciones Fiserv huérfanas para asociar")
                return

            _logger.info(
                "Encontradas %s transacciones Fiserv huérfanas para evaluar",
                len(orphaned_transactions),
            )

            matching_transaction = None
            best_score = 0

            for transaction in orphaned_transactions:
                score = 0

                if abs(transaction.amount - payment_amount) < 0.01:
                    score += 100
                    _logger.info(
                        "Coincidencia exacta de monto: Transacción %s (%.2f) = Pago %s (%.2f)",
                        transaction.fiserv_transaction_id,
                        transaction.amount,
                        payment_name,
                        payment_amount,
                    )
                elif abs(transaction.amount - payment_amount) < 1.0:
                    score += 50
                    _logger.info(
                        "Coincidencia aproximada de monto: Transacción %s (%.2f) ≈ Pago %s (%.2f)",
                        transaction.fiserv_transaction_id,
                        transaction.amount,
                        payment_name,
                        payment_amount,
                    )

                if transaction.pos_payment_id:
                    existing_payment_name = (
                        getattr(transaction.pos_payment_id, "name", "Unknown") or "Unknown"
                    )
                    _logger.info(
                        "Transacción %s ya asociada a pago %s, saltando...",
                        transaction.fiserv_transaction_id,
                        existing_payment_name,
                    )
                    continue

                if score > best_score:
                    best_score = score
                    matching_transaction = transaction
                    _logger.info(
                        "Nueva mejor coincidencia: Transacción %s (Score: %s)",
                        transaction.fiserv_transaction_id,
                        score,
                    )

            if matching_transaction and best_score > 0:
                matching_transaction.pos_payment_id = self.id
                self.payment_transaction_id = matching_transaction.id

                if not matching_transaction.pos_order_id and self.pos_order_id:
                    matching_transaction.pos_order_id = self.pos_order_id.id
                    order_name = getattr(self.pos_order_id, "name", None)
                    if order_name:
                        matching_transaction.invoice_number = order_name

                order_name = (
                    getattr(self.pos_order_id, "name", "None")
                    if self.pos_order_id
                    else "None"
                )
                _logger.info(
                    "Transacción Fiserv asociada exitosamente: %s -> Pago: %s, Orden: %s (Score: %s)",
                    matching_transaction.fiserv_transaction_id,
                    payment_name,
                    order_name,
                    best_score,
                )
            else:
                _logger.warning(
                    "No se encontró transacción Fiserv para el pago: %s (Monto: %s)",
                    payment_name,
                    payment_amount,
                )

        except Exception as e:
            _logger.error("Error al asociar transacción Fiserv con pago ID %s: %s", self.id, str(e))
