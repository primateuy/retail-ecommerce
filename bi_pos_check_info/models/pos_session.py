# -*- coding: utf-8 -*-
"""
Extensión de sesión POS: creación de cheques de terceros estándar (l10n_latam_check).

El flujo nativo de Odoo solo genera un account.payment genérico al cerrar sesión.
Si el pago tiene datos de cheque (bi_pos_check_info) y el diario expone el método
«Nuevo cheque de terceros», se crea el account.payment con ese método para que el
cheque quede registrado como en contabilidad manual.
"""

import logging

from odoo import _, models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result["search_params"]["fields"].append("allow_check_info")
        return result

    def _get_pos_ui_pos_res_banks(self, params):
        # sudo: lectura transparente para usuarios PDV sin permisos contables.
        banks = self.env["res.bank"].sudo().search_read(**params["search_params"])
        return banks

    def _get_pos_ui_stock_picking_type(self, params):
        # sudo: el usuario PDV puede no tener visibilidad sobre el stock.picking.type
        # del POS (reglas de registro por almacén/compañía). Sin sudo, el search_read
        # del core devuelve [] y el [0] revienta con IndexError, cortando la carga.
        result = self.env['stock.picking.type'].sudo().search_read(
            **params['search_params']
        )
        return result[0] if result else {}

    def load_pos_data(self):
        loaded_data = {}
        self = self.with_context(loaded_data=loaded_data)
        for model in self._pos_ui_models_to_load():
            loaded_data[model] = self._load_model(model)
        self._pos_data_process(loaded_data)
        bank_data = self._get_pos_ui_pos_res_banks(self._loader_params_pos_res_banks())
        loaded_data["banks"] = bank_data
        return loaded_data

    def _loader_params_pos_res_banks(self):
        return {
            "search_params": {
                "domain": [],
                "fields": [],
            },
        }

    def _create_split_account_payment(self, payment, amounts):
        """
        Si el pos.payment trae datos de cheque y el diario está preparado para
        cheques de terceros (l10n_latam_check), crea el account.payment con el
        método «new_third_party_checks» y número/banco/emisor tomados del POS.
        """
        payment_method = payment.payment_method_id
        if (
            payment_method.journal_id
            and payment_method.allow_check_info
            and getattr(payment, "check_number", False)
        ):
            pm_line = payment_method.journal_id._get_available_payment_method_lines(
                "inbound"
            ).filtered(lambda line: line.code == "new_third_party_checks")[:1]
            if pm_line:
                return self._bi_pos_create_split_third_party_check_payment(
                    payment, amounts, pm_line
                )
            _logger.warning(
                "POS Check Info: el diario «%s» no tiene línea de método de pago "
                "inbound «new_third_party_checks». Revise l10n_latam_check y la "
                "configuración del diario del método POS.",
                payment_method.journal_id.display_name,
            )
        return super()._create_split_account_payment(payment, amounts)

    def _bi_pos_create_split_third_party_check_payment(self, payment, amounts, pm_line):
        """
        Replica la lógica estándar de _create_split_account_payment pero fija el
        método de pago de cheque de terceros y los campos requeridos por
        l10n_latam_check.
        """
        self.ensure_one()
        payment_method = payment.payment_method_id
        outstanding_account = (
            payment_method.outstanding_account_id
            or self.company_id.account_journal_payment_debit_account_id
        )
        accounting_partner = self.env["res.partner"]._find_accounting_partner(
            payment.partner_id
        )
        destination_account = accounting_partner.property_account_receivable_id

        if float_compare(amounts["amount"], 0, precision_rounding=self.currency_id.rounding) < 0:
            outstanding_account, destination_account = destination_account, outstanding_account

        issuer_vat = accounting_partner.vat or (payment.check_owner or "").strip() or False

        payment_reference = False
        if getattr(payment, "check_bank_account", False):
            payment_reference = (payment.check_bank_account or "")[:200]

        account_payment = self.env["account.payment"].create(
            {
                "amount": abs(amounts["amount"]),
                "partner_id": accounting_partner.id,
                "journal_id": payment_method.journal_id.id,
                "force_outstanding_account_id": outstanding_account.id,
                "destination_account_id": destination_account.id,
                "ref": _(
                    "%s POS payment of %s in %s",
                    payment_method.name,
                    payment.partner_id.display_name,
                    self.name,
                ),
                "payment_reference": payment_reference,
                "pos_payment_method_id": payment_method.id,
                "pos_session_id": self.id,
                "payment_method_line_id": pm_line.id,
                "payment_type": "inbound",
                "partner_type": "customer",
                "company_id": self.company_id.id,
                "check_number": payment.check_number,
            }
        )
        account_payment.write(
            {
                "l10n_latam_check_bank_id": payment.bank_id.id if payment.bank_id else False,
                "l10n_latam_check_issuer_vat": issuer_vat,
            }
        )
        account_payment.action_post()
        _logger.info(
            "POS Check Info: account.payment id=%s (cheque terceros) creado para pos.payment id=%s.",
            account_payment.id,
            payment.id,
        )
        return account_payment.move_id.line_ids.filtered(
            lambda line: line.account_id == account_payment.destination_account_id
        )
