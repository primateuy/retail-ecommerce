# -*- coding: utf-8 -*-
"""
Extensión de payment.transaction para el flujo POS OCA.

Aporta los campos ``pos_order_id`` / ``pos_payment_id`` y los hooks que
sincronizan con ``pos.payment``. Vive aquí (no en odoo_pos_oca_core) para que
el core no arrastre dependencia de point_of_sale: el core es el sustrato
compartido entre POS y backend contable.
"""

import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Pedido POS',
        help='Pedido del punto de venta que generó la transacción',
    )

    pos_payment_id = fields.Many2one(
        'pos.payment',
        string='Pago POS',
        help='Pago del punto de venta que generó la transacción',
    )

    oca_respaldo_payment_id = fields.Many2one(
        'pos.payment',
        string='Registrado por respaldo en',
        ondelete='set null',
        index=True,
        copy=False,
        readonly=True,
        help='Pago del PDV con el que la cajera registró este cobro por el POS de respaldo, '
             'con la misma autorización, porque la caja no recibió la respuesta del pinpad. '
             'El cobro está en esa venta: no es un cobro sin venta.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        transacciones = super().create(vals_list)
        transacciones._oca_marcar_cobro_registrado_por_respaldo()
        return transacciones

    def write(self, vals):
        """
        Mantiene en sincronía ``pos.payment.payment_transaction_id`` cuando
        cambia ``pos_payment_id`` en la transacción. Limpia el campo del pago
        anterior y lo vuelve a setear en el nuevo, asegurando referencia
        bidireccional única.
        """
        if 'pos_payment_id' in vals:
            new_payment_id = vals['pos_payment_id']
            for tx in self:
                old_payment = tx.pos_payment_id
                if old_payment and old_payment.id != new_payment_id:
                    if old_payment.exists():
                        old_payment.payment_transaction_id = False
                if new_payment_id:
                    new_payment = self.env['pos.payment'].browse(new_payment_id)
                    if new_payment.exists():
                        new_payment.payment_transaction_id = tx.id
        return super().write(vals)

    def update_payment_transaction_reference(self):
        """
        Refuerza la referencia bidireccional pago POS ↔ transacción.

        Se llama desde flujos donde la transacción se vinculó al pos.payment a
        posteriori (por ejemplo, asociación diferida tras crear la orden POS).
        """
        for transaction in self:
            if transaction.pos_payment_id:
                transaction.pos_payment_id.payment_transaction_id = transaction.id
                _logger.info(
                    'Campo payment_transaction_id actualizado en pago %s para transacción %s',
                    transaction.pos_payment_id.name,
                    transaction.oca_transaction_id,
                )

    # --- Cobro registrado por el POS de respaldo (Forum, 2026-11-20) ---

    def _oca_marcar_cobro_registrado_por_respaldo(self):
        """Marca el cobro del pinpad que estas transacciones registraron por respaldo.

        Cuando la caja no recibe la respuesta del pinpad, la cajera pasa la venta por un
        método manual con la autorización del cobro. El cobro OCA quedaba sin venta y
        aparecía como cobro suelto: el 19 y 20-11-2026, 20 de 28. Se toma como la misma
        operación el cobro OCA aprobado, sin pago del PDV, con la misma autorización, de
        una terminal de esa caja y de las 24 h anteriores.

        Returns:
            payment.transaction: los cobros OCA marcados.
        """
        marcados = self.browse()
        for manual in self:
            if manual.provider_code == 'oca' or not manual.pos_payment_id:
                continue
            autorizacion = (manual.authorization_code or '').strip()
            if not autorizacion:
                continue
            pago = manual.pos_payment_id
            terminales = [
                t for t in pago.session_id.config_id.payment_method_ids.mapped('codigo_terminal') if t
            ]
            if not terminales:
                continue
            hasta = manual.create_date or fields.Datetime.now()
            cobros = self.sudo().search([
                ('provider_id.code', '=', 'oca'),
                ('state', '=', 'done'),
                ('authorization_code', '=', autorizacion),
                ('pos_id', 'in', terminales),
                ('pos_payment_id', '=', False),
                ('oca_reverso_de_id', '=', False),
                ('oca_respaldo_payment_id', '=', False),
                ('create_date', '<=', hasta),
                ('create_date', '>=', hasta - timedelta(days=1)),
            ])
            for cobro in cobros:
                if cobro.amount <= 0 or cobro._oca_pago_pos_del_cobro():
                    continue
                cobro.oca_respaldo_payment_id = pago
                marcados |= cobro
                _logger.info(
                    'OCA: el cobro %s (aut. %s) se registró por respaldo en la venta %s; '
                    'no es un cobro sin venta.',
                    cobro.oca_transaction_id, autorizacion,
                    pago.pos_order_id.pos_reference or pago.pos_order_id.name,
                )
        return marcados

    # --- Anular / devolver desde la transacción: razones que sólo ve el POS ---

    def _oca_pago_pos_del_cobro(self):
        """Pago del PDV que usó este cobro, aunque ``pos_payment_id`` no se haya completado.

        La asociación de la transacción con el pago a veces no se escribe, pero el
        ``pos.payment`` guarda igual el id de OCA: buscar por los dos. Un cobro registrado
        por el POS de respaldo está en la venta de ese pago.
        """
        self.ensure_one()
        if self.pos_payment_id:
            return self.pos_payment_id
        if self.oca_respaldo_payment_id:
            return self.oca_respaldo_payment_id
        tid = (self.oca_transaction_id or '').strip()
        if not tid:
            return self.env['pos.payment']
        return self.env['pos.payment'].sudo().search([('transaction_id', '=', tid)], limit=1)

    def _oca_advertencias_reverso(self):
        advertencias = super()._oca_advertencias_reverso()
        pago = self._oca_pago_pos_del_cobro()
        if pago:
            advertencias.append(_(
                'El cobro está en la venta %s: anulándolo desde acá NO se emite la nota de '
                'crédito y la venta queda como cobrada. Lo normal es devolverlo desde el PDV.'
            ) % (pago.pos_order_id.pos_reference or pago.pos_order_id.name or ''))
        return advertencias

    def _oca_advertencias_pago_asociado(self):
        advertencias = super()._oca_advertencias_pago_asociado()
        pago = self._oca_pago_pos_del_cobro()
        if pago or self.pos_order_id:
            orden = pago.pos_order_id or self.pos_order_id
            advertencias.append(_(
                'El cobro ya está en la venta %s del PDV: su ingreso entra con el cierre de la '
                'caja, y un pago contable además lo deja dos veces.'
            ) % (orden.pos_reference or orden.name or ''))
        return advertencias
