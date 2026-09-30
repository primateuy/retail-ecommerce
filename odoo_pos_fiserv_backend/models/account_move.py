# -*- coding: utf-8 -*-
"""
Extensión de ``account.move``: el botón «Pagar» de la factura abre directamente
el formulario de ``account.payment`` con la/s factura/s precargadas, donde está
«Crear transacción». El wizard estándar no sirve para Fiserv: confirma el pago
al crearlo y el cobro en el pinpad tiene que ir antes.

19.0: el reemplazo del botón SÓLO aplica si la compañía tiene un proveedor
Fiserv habilitado. En 17.0 bastaba con instalar el módulo para que a todos se
les cambiara «Registrar pago», aunque Fiserv no estuviera en uso.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    fiserv_register_enabled = fields.Boolean(
        compute='_compute_fiserv_register_enabled',
        help='Técnico: hay un proveedor Fiserv habilitado en la compañía de la '
             'factura, así que «Pagar» abre el form del pago.',
    )
    # Si otro backend integrado (OCA) está instalado en la BD, éste sobreescribe
    # el compute para devolver True y ocultar el botón duplicado de Fiserv.
    pos_register_hide_fiserv = fields.Boolean(
        compute='_compute_pos_register_hide_fiserv',
        help='Flag técnico que oculta el botón «Pagar» de Fiserv cuando hay '
             'otro backend POS integrado que aporta el suyo.',
    )

    @api.depends('company_id')
    def _compute_fiserv_register_enabled(self):
        # sudo: payment.provider es de Ajustes; se lee sólo si hay uno activo.
        activas = set(self.env['payment.provider'].sudo().search([
            ('code', '=', 'fiserv'), ('state', '!=', 'disabled'),
        ]).company_id.ids)
        for move in self:
            move.fiserv_register_enabled = move.company_id.id in activas

    def _compute_pos_register_hide_fiserv(self):
        for rec in self:
            rec.pos_register_hide_fiserv = False

    def _fiserv_register_payment_context(self, invoices):
        """Contexto por defecto del pago que abre «Pagar» (el puente lo extiende)."""
        partners = invoices.mapped('partner_id')
        move_types = set(invoices.mapped('move_type'))
        outbound_types = {'in_invoice', 'out_refund'}
        first = invoices[0]
        return {
            'default_partner_id': partners.id,
            'default_partner_type': 'customer' if first.move_type in ('out_invoice', 'out_refund') else 'supplier',
            'default_payment_type': 'outbound' if move_types & outbound_types else 'inbound',
            'default_amount': sum(inv.amount_residual for inv in invoices),
            'default_currency_id': first.currency_id.id,
            'default_company_id': first.company_id.id,
            'default_memo': ', '.join(invoices.mapped('name')),
            'default_fiserv_source_invoice_ids': [(6, 0, invoices.ids)],
        }

    def action_fiserv_register_payment(self):
        """
        Abre el formulario de ``account.payment`` con la/s factura/s precargadas.
        Asume agrupado (mismo partner, mismo signo) con varias facturas.
        """
        invoices = self.filtered(lambda m: m.state == 'posted' and m.payment_state in (
            'not_paid', 'partial', 'in_payment'
        ) and m.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'))
        if not invoices:
            raise UserError(_('Seleccione al menos una factura publicada con saldo pendiente.'))
        if len(invoices.mapped('partner_id')) > 1:
            raise UserError(_(
                'Para registrar un pago agrupado, todas las facturas deben tener el mismo contacto.'))
        move_types = set(invoices.mapped('move_type'))
        if move_types & {'in_invoice', 'out_refund'} and move_types & {'out_invoice', 'in_refund'}:
            raise UserError(_('No se pueden mezclar facturas de cobro y de pago en un mismo registro.'))
        if len(invoices.company_id) > 1:
            raise UserError(_('Las facturas deben ser de la misma compañía.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Registrar pago'),
            'res_model': 'account.payment',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': self._fiserv_register_payment_context(invoices),
        }
