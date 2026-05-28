# -*- coding: utf-8 -*-
"""Propaga el folio del talonario (guardado en `pos.payment.user_payment_reference`
por el módulo `pos_reference_for_payment`) al campo `payment_reference` del
account.move generado, ANTES de que action_post() valide el folio.

El backend `l10n_uy_cfc_efac.account_move.action_post` lee `payment_reference`
para validar contra el CAE. Si llega vacío, la validación falla con UserError.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _prepare_invoice_vals(self):
        """Inyecta `payment_reference` en los vals de la factura ANTES de que
        Odoo la cree. Esto garantiza que cuando action_post() corra (dentro
        del flujo normal de creación de factura POS), el folio ya esté en
        el move.

        Se busca el folio en las paymentLines de la orden POS, donde
        `pos_reference_for_payment` lo guarda en `user_payment_reference`.
        """
        vals = super()._prepare_invoice_vals()
        if not self.config_id.journal_id.es_diario_contingencia:
            return vals
        ref = self._get_cfc_folio()
        if ref:
            vals['payment_reference'] = ref
        return vals

    def _get_cfc_folio(self):
        """Devuelve el folio CFC ingresado por el cajero (string).

        Busca en `pos.payment.user_payment_reference` de las paymentLines
        de esta orden. Si hay múltiples, toma el último no vacío.
        """
        self.ensure_one()
        if not hasattr(self.payment_ids, 'user_payment_reference'):
            return ''
        refs = self.payment_ids.filtered(lambda p: p.user_payment_reference)
        if not refs:
            return ''
        return refs[-1].user_payment_reference or ''
