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

Órdenes que llegan sin folio válido
-----------------------------------
Si una orden de contingencia se sincroniza sin folio, o con uno que el CAE
rechaza, facturarla hace fallar TODA la sincronización: la orden queda en la
cola del navegador y repite el error en cada reintento, para siempre. Eso pasa
con las órdenes validadas antes de este arreglo, y puede pasar si el POS no
pudo cargar los datos del CAE y el rango no se controló en el frontend.

En ese caso la orden se guarda pagada y sin facturar, con el motivo en
`cfc_problema_sync`; desde el backend se carga el folio en la orden y se
factura. Es el mismo criterio que usan `odoo_pos_oca` y `odoo_pos_fiserv_pos`
cuando falla la factura de un cobro ya hecho.

El motivo va en un campo y no en el chatter porque en 17 `pos.order` no hereda
`mail.thread`: `message_post` no existe.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

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
    cfc_es_contingencia = fields.Boolean(
        string='PDV de contingencia',
        compute='_compute_cfc_es_contingencia',
    )
    cfc_problema_sync = fields.Char(
        string='Motivo por el que no se facturó',
        copy=False,
        readonly=True,
        help='La orden de contingencia se sincronizó sin un folio utilizable y '
             'se guardó sin facturar. Cargue el folio correcto y facture la '
             'orden desde el backend.',
    )

    @api.depends('config_id.invoice_journal_id.es_diario_contingencia')
    def _compute_cfc_es_contingencia(self):
        for order in self:
            order.cfc_es_contingencia = bool(order.config_id._cfc_journal())

    @api.model
    def _order_fields(self, ui_order):
        """Toma `cfc_folio` del JSON que manda el POS."""
        fields_vals = super()._order_fields(ui_order)
        fields_vals['cfc_folio'] = ui_order.get('cfc_folio') or False
        return fields_vals

    def _process_saved_order(self, draft):
        """Si la orden de contingencia no trae un folio utilizable, se guarda
        sin facturar en vez de tirar abajo la sincronización.

        Se hace acá porque es donde el core decide facturar
        (`if self.to_invoice and self.state == 'paid'`).
        """
        if not draft and self.to_invoice:
            problema = self._cfc_problema_folio()
            if problema:
                _logger.warning(
                    "[CFC] La orden %s no se factura al sincronizar: %s",
                    self.pos_reference, problema,
                )
                self.write({'to_invoice': False, 'cfc_problema_sync': problema})
        return super()._process_saved_order(draft)

    def _cfc_problema_folio(self):
        """Devuelve por qué no se puede facturar la orden con su folio, o
        None si se puede (o si la orden no es de contingencia)."""
        self.ensure_one()
        journal = self.config_id._cfc_journal()
        if not journal:
            return None
        cae = journal.cae_activo_id
        if not cae:
            return _("No hay un CAE de contingencia activo para el diario '%s'.") % journal.name
        ok, msg = cae.validar_folio(self._get_cfc_folio())
        return None if ok else msg

    def _prepare_invoice_vals(self):
        """Inyecta `payment_reference` en los vals de la factura ANTES de que
        Odoo la cree. Esto garantiza que cuando action_post() corra (dentro
        del flujo normal de creación de factura POS), el folio ya esté en
        el move.

        Se mira el diario de la FACTURA, que es el que valida
        `l10n_uy_cfc_efac` en `_post`, y no `config_id.journal_id`.
        """
        vals = super()._prepare_invoice_vals()
        journal = self.env['account.journal'].sudo().browse(vals.get('journal_id'))
        if not journal.es_diario_contingencia:
            return vals
        ref = self._get_cfc_folio()
        if not ref:
            raise UserError(_(
                "La orden %s es de un PDV de contingencia y no tiene folio. "
                "Cargue el número en el campo 'Folio del talonario de "
                "contingencia' de la orden antes de facturarla."
            ) % self.name)
        vals['payment_reference'] = ref
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
