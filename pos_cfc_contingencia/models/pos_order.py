# -*- coding: utf-8 -*-
"""Propaga el folio del talonario de contingencia al `payment_reference` del
account.move generado, ANTES de que action_post() lo valide.

El backend `l10n_uy_cfc_efac.account_move.action_post` lee `payment_reference`
para validar contra el CAE. Si llega vacío, la validación falla con UserError.

De dónde sale el folio
----------------------
El POS lo guarda en la propia orden (`cfc_folio`) y viaja con ella en
`export_as_JSON`. Antes se dependía de `pos.payment.user_payment_reference`,
que llena `pos_reference_for_payment` con un RPC posterior a la validación: ese
camino solo funciona si está activo su ajuste `is_allow_payment_ref` y si el
cajero se acuerda de apretar el botón "Payment Reference". Se mantiene como
respaldo para las órdenes viejas y para quien siga usando ese botón.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cfc_folio = fields.Char(
        string='Folio del talonario de contingencia',
        copy=False,
        index=True,
        help='Número de folio del talonario físico que el cajero ingresó en el '
             'PDV de contingencia. Viaja con la orden desde el POS.',
    )

    @api.model
    def _order_fields(self, ui_order):
        """Toma `cfc_folio` del JSON que manda el POS."""
        fields_vals = super()._order_fields(ui_order)
        fields_vals['cfc_folio'] = ui_order.get('cfc_folio') or False
        return fields_vals

    def _prepare_invoice_vals(self):
        """Inyecta `payment_reference` en los vals de la factura ANTES de que
        Odoo la cree. Esto garantiza que cuando action_post() corra (dentro
        del flujo normal de creación de factura POS), el folio ya esté en
        el move.
        """
        vals = super()._prepare_invoice_vals()
        if not self.config_id.journal_id.es_diario_contingencia:
            return vals
        ref = self._get_cfc_folio()
        if ref:
            vals['payment_reference'] = ref
        else:
            _logger.warning(
                "[CFC] La orden %s es de un PDV de contingencia y no trae "
                "folio: action_post() va a rechazar la factura.", self.name,
            )
        return vals

    def _get_cfc_folio(self):
        """Devuelve el folio CFC ingresado por el cajero (string).

        Primero el campo propio de la orden; si no está —órdenes anteriores a
        la 17.0.1.1.0, o cajeros que usaron el botón de
        `pos_reference_for_payment`— se cae al `user_payment_reference` de las
        líneas de pago.
        """
        self.ensure_one()
        if self.cfc_folio:
            return self.cfc_folio.strip()
        if 'user_payment_reference' not in self.env['pos.payment']._fields:
            return ''
        refs = self.payment_ids.filtered(lambda p: p.user_payment_reference)
        if not refs:
            return ''
        return (refs[-1].user_payment_reference or '').strip()
