# -*- coding: utf-8 -*-
"""
Extensión de ``account.move`` para reemplazar la acción estándar «Registrar pago»
(wizard ``account.payment.register``) por una acción que abre directamente el
formulario de ``account.payment`` con la/s factura/s precargadas.

El nuevo flujo permite al usuario usar el botón «Crear transacción» del form de
pago (integración Fiserv) en lugar de pasar por el wizard estándar.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Si otro backend integrado (OCA) está instalado en la BD, éste sobreescribe
    # el compute para devolver True y ocultar el botón duplicado de Fiserv.
    # Así se evita que en el form de factura aparezcan dos botones idénticos
    # "Registrar pago" cuando Fiserv y OCA coexisten.
    pos_register_hide_fiserv = fields.Boolean(
        compute='_compute_pos_register_hide_fiserv',
        help='Flag técnico que oculta el botón «Registrar pago» de Fiserv '
        'cuando hay otro backend POS integrado que aporta el suyo.',
    )

    def _compute_pos_register_hide_fiserv(self):
        # Fiserv por defecto no oculta su botón; OCA sobrescribe este compute
        # para retornar True cuando está instalado.
        for rec in self:
            rec.pos_register_hide_fiserv = False

    def action_fiserv_register_payment(self):
        """
        Abre el formulario de ``account.payment`` con los datos de la/s factura/s
        ya precargados. Asume agrupado (mismo partner, mismo signo) cuando se
        invoca con varias facturas.

        Se reemplaza la acción estándar por esta para que el usuario caiga
        directamente en el form del pago y pueda usar «Crear transacción»
        cuando el diario elegido sea integrado Fiserv.
        """
        invoices = self.filtered(lambda m: m.state == 'posted' and m.payment_state in (
            'not_paid', 'partial', 'in_payment'
        ) and m.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'))
        if not invoices:
            raise UserError(
                _('Seleccione al menos una factura publicada con saldo pendiente.')
            )
        partners = invoices.mapped('partner_id')
        if len(partners) > 1:
            raise UserError(
                _('Para registrar un pago agrupado, todas las facturas deben tener el mismo contacto.')
            )
        move_types = set(invoices.mapped('move_type'))
        outbound_types = {'in_invoice', 'out_refund'}
        inbound_types = {'out_invoice', 'in_refund'}
        if move_types & outbound_types and move_types & inbound_types:
            raise UserError(
                _('No se pueden mezclar facturas de cobro y de pago en un mismo registro.')
            )

        first = invoices[0]
        payment_type = 'outbound' if move_types & outbound_types else 'inbound'
        partner_type = 'customer' if first.move_type in ('out_invoice', 'out_refund') else 'supplier'
        amount_total = sum(inv.amount_residual for inv in invoices)

        ctx = {
            'default_partner_id': partners.id,
            'default_partner_type': partner_type,
            'default_payment_type': payment_type,
            'default_amount': amount_total,
            'default_currency_id': first.currency_id.id,
            'default_company_id': first.company_id.id,
            'default_ref': ', '.join(invoices.mapped('name')),
            'default_fiserv_source_invoice_ids': [(6, 0, invoices.ids)],
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Registrar pago'),
            'res_model': 'account.payment',
            'view_mode': 'form',
            'target': 'current',
            'context': ctx,
        }
