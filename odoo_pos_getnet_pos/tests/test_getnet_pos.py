# -*- coding: utf-8 -*-
"""
Tests del flujo POS Getnet (lado servidor): FacturaNro provisional,
enviar_pago con SOAP mockeado (lock incluido), worker sincrónico con bus,
y asociación transacción-orden por referencia y por monto.
"""

import uuid
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils
from odoo.addons.odoo_pos_getnet_core.models import (
    payment_transaction as pt_mod,
)

# Nombres del WSDL real (enum de strings, Resp_TransaccionFinalizada).
APROBADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE',
    'Resp_TransaccionFinalizada': 'true',
    'Aprobada': 'true',
    'Ticket': '333',
    'Lote': '9',
    'NroAutorizacion': 'C777',
    'TarjetaTipo': 'DEB',
    'MsgRespuesta': 'APROBADA',
    'Voucher': ['V LINEA 1', 'V LINEA 2'],
}
DENEGADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_ERROR',
    'Resp_TransaccionFinalizada': 'true',
    'Aprobada': 'false',
    'CodRespAdq': '51',
    'Lote': '0',
    'Ticket': '0',
    'MsgRespuesta': 'DENEGADA',
}


@tagged('post_install', '-at_install')
class TestGetnetPos(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Getnet POS Test',
            'code': 'getnet',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE',
            'getnet_emp_hash': 'HASH',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Caja POS',
            'term_cod': 'T00003',
            'payment_provider_id': cls.provider.id,
        })
        cls.method = cls.env['pos.payment.method'].create({
            'name': 'Getnet TPV',
            'use_payment_terminal': 'getnet',
            'getnet_provider_id': cls.provider.id,
            'getnet_terminal_id': cls.terminal.id,
        })
        cls.config = cls.env['pos.config'].create({'name': 'Caja Getnet Test'})
        cls.config.write({'payment_method_ids': [(4, cls.method.id)]})
        cls.session = cls.env['pos.session'].create({
            'config_id': cls.config.id,
            'user_id': cls.env.uid,
        })
        cls.env['payment.transaction'].search([
            ('provider_id.code', '=', 'getnet'),
            ('state', 'in', ('draft', 'pending')),
            ('getnet_token', '!=', False),
        ]).write({'getnet_token': False})

    def _data(self, **vals):
        base = {
            'amount': 150.0,
            'currency_id': self.env.company.currency_id.id,
            'session_id': self.session.id,
            'config_id': self.config.id,
            'tracking_number': 'A0042',
            'order_uid': '00001-001-0001',
            'is_refund': False,
            'refunded_order_ids': [],
        }
        base.update(vals)
        return base

    def test_factura_nro_cero_en_el_pos(self):
        """
        En el TPV se cobra antes de emitir el CFE: no hay número real, se
        manda 0. Omitirlo no es opción (el concentrador da rc=2).
        """
        self.assertEqual(self.method._get_pos_factura_nro(
            {'tracking_number': 'A0042'}), 0)
        self.assertEqual(self.method._get_pos_factura_nro({}), 0)

    def test_envelope_pos_con_factura_nro_y_sin_montos(self):
        """El posteo del TPV lleva FacturaNro=0 y ningún monto de factura."""
        payload = self.provider._getnet_base_transaccion_vals(self.terminal)
        payload['Operacion'] = getnet_utils.GETNET_OPERACION_VENTA
        payload['MonedaISO'] = getnet_utils.GETNET_MONEDA_ISO['UYU']
        payload['Monto'] = getnet_utils.getnet_centavos(150.0)
        factura_nro = self.method._get_pos_factura_nro({})
        if factura_nro is not None:
            payload['FacturaNro'] = factura_nro
        envelope = getnet_utils.getnet_build_soap_envelope(
            'PostearTransaccion', {'Transaccion': payload}).decode('utf-8')
        self.assertIn('<dc:FacturaNro>0</dc:FacturaNro>', envelope)
        for clave in ('FacturaMonto', 'FacturaMontoGravado',
                      'FacturaMontoIVA', 'FacturaConsumidorFinal'):
            self.assertNotIn(clave, envelope)
        self.assertIn('<dc:Operacion>VTA</dc:Operacion>', envelope)

    def test_enviar_pago_ok_toma_lock_y_lanza_worker(self):
        lanzado = []

        def fake_soap(prov, method, params):
            return ({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-POS-1',
                     'TokenSegundosConsultar': '5'}, '<req/>', '<resp/>')

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(type(self.method), '_getnet_start_pos_worker',
                             lambda s, *a: lanzado.append(a)):
            resp = self.method.getnet_enviar_pago(self._data())
        self.assertEqual(resp['rc'], 0)
        self.assertEqual(resp['token'], 'TOK-POS-1')
        self.assertEqual(len(lanzado), 1)
        tx = self.env['payment.transaction'].search([
            ('reference', '=', resp['tx_reference'])])
        self.assertEqual(tx.getnet_token, 'TOK-POS-1')
        # El lock quedó tomado para el worker (el POS no lo bypasea)
        with self.assertRaises(UserError):
            self.terminal.getnet_claim('account_payment')
        self.terminal.getnet_release()

    def test_enviar_pago_rechazado_libera_lock(self):
        def fake_soap(prov, method, params):
            return ({'Resp_CodigoRespuesta': '2',
                     'Resp_MensajeError': 'Error de integración'},
                    '<req/>', '<resp/>')

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            resp = self.method.getnet_enviar_pago(self._data())
        self.assertEqual(resp['rc'], 2)
        tx = self.env['payment.transaction'].search([
            ('reference', '=', resp['tx_reference'])])
        self.assertEqual(tx.state, 'error')
        self.assertTrue(self.terminal.getnet_claim('pos'))
        self.terminal.getnet_release()

    def test_worker_inner_notifica_bus(self):
        method_pm = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': method_pm.id,
            'reference': 'GETNET-POS-%s' % uuid.uuid4().hex[:10],
            'amount': 150.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'getnet_token': 'TOK-POS-2',
            'getnet_terminal_id': self.terminal.id,
            'getnet_transaction_origin': 'pos_payment',
        })

        def fake_soap(prov, method, params):
            return (dict(APROBADA), '<req/>', '<resp/>')

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None), \
                patch.object(pt_mod.time, 'monotonic', side_effect=[0, 5]):
            payload = self.method._getnet_pos_worker_inner(
                tx, self.terminal, self.provider, 1,
                self.session._get_bus_channel_name(), self.config.id)
        self.assertTrue(payload['approved'])
        self.assertEqual(payload['ticket'], '333')
        self.assertEqual(payload['id_config'], self.config.id)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.getnet_voucher, 'V LINEA 1\nV LINEA 2')

    def test_worker_inner_denegada_no_resuelve_la_linea(self):
        """
        Finalizada con error: el payload del bus va approved=False (la
        línea del TPV NO se resuelve como cobrada) y no queda lote.
        """
        method_pm = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': method_pm.id,
            'reference': 'GETNET-POS-%s' % uuid.uuid4().hex[:10],
            'amount': 150.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'getnet_token': 'TOK-POS-DEN',
            'getnet_terminal_id': self.terminal.id,
            'getnet_transaction_origin': 'pos_payment',
        })

        def fake_soap(prov, method, params):
            return (dict(DENEGADA), '<req/>', '<resp/>')

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None), \
                patch.object(pt_mod.time, 'monotonic', side_effect=[0, 5]):
            payload = self.method._getnet_pos_worker_inner(
                tx, self.terminal, self.provider, 1,
                self.session._get_bus_channel_name(), self.config.id)
        self.assertFalse(payload['approved'])
        self.assertEqual(payload['state'], 'error')
        self.assertEqual(tx.state, 'error')
        self.assertFalse(tx.getnet_lote)
        self.assertFalse(self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id)]))

    def test_devolucion_requiere_tx_original(self):
        with self.assertRaises(UserError):
            self.method._getnet_ticket_original_for_refund(
                {'refunded_order_ids': [999999]})

    def test_asociacion_referencia_y_fallback_monto(self):
        method_pm = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')

        def crear_tx(ref, amount):
            tx = self.env['payment.transaction'].create({
                'provider_id': self.provider.id,
                'payment_method_id': method_pm.id,
                'reference': ref,
                'amount': amount,
                'currency_id': self.env.company.currency_id.id,
                'partner_id': self.env.company.partner_id.id,
                'getnet_transaction_origin': 'pos_payment',
            })
            tx._set_done()
            return tx

        tx_ref = crear_tx('GETNET-POS-REF-%s' % uuid.uuid4().hex[:6], 80.0)
        tx_amt = crear_tx('GETNET-POS-AMT-%s' % uuid.uuid4().hex[:6], 55.5)
        order = self.env['pos.order'].create({
            'session_id': self.session.id,
            'amount_total': 135.5, 'amount_tax': 0.0,
            'amount_paid': 135.5, 'amount_return': 0.0,
        })
        self.env['pos.payment'].create({
            'pos_order_id': order.id, 'amount': 80.0,
            'payment_method_id': self.method.id,
            'transaction_id': tx_ref.reference,
        })
        self.env['pos.payment'].create({
            'pos_order_id': order.id, 'amount': 55.5,
            'payment_method_id': self.method.id,
        })
        order._getnet_associate_transactions()
        self.assertEqual(tx_ref.getnet_pos_order_id, order)
        self.assertEqual(tx_amt.getnet_pos_order_id, order)
        # Voucher recuperable para reimpresión
        tx_ref.getnet_voucher = 'LINEA X'
        info = order.get_getnet_voucher()
        self.assertIn(info['ticket'], (tx_ref.getnet_ticket or '',
                                       tx_amt.getnet_ticket or '', ''))

    # ------------------------------------------------------------------
    # Multi-terminal: una caja por pinpad
    # ------------------------------------------------------------------
    def _segunda_caja(self):
        """Segunda caja con su propio pinpad (T00004)."""
        terminal2 = self.env['getnet.pos.terminal'].create({
            'name': 'Caja POS 2',
            'term_cod': 'T00004',
            'payment_provider_id': self.provider.id,
        })
        metodo2 = self.env['pos.payment.method'].create({
            'name': 'Getnet TPV 2',
            'use_payment_terminal': 'getnet',
            'getnet_provider_id': self.provider.id,
            'getnet_terminal_id': terminal2.id,
        })
        config2 = self.env['pos.config'].create({'name': 'Caja Getnet Test 2'})
        config2.write({'payment_method_ids': [(6, 0, [metodo2.id])]})
        session2 = self.env['pos.session'].create({
            'config_id': config2.id,
            'user_id': self.env.uid,
        })
        return terminal2, metodo2, session2

    def test_terminal_del_metodo_de_pago_por_caja(self):
        """Cada método de pago resuelve SU pinpad, no el primero que haya."""
        terminal2, metodo2, _session2 = self._segunda_caja()
        self.assertEqual(self.method._getnet_terminal(), self.terminal)
        self.assertEqual(metodo2._getnet_terminal(), terminal2)

    def test_metodo_sin_terminal_con_varias_exige_configurarla(self):
        """Con más de una terminal el atajo del proveedor ya no aplica."""
        self._segunda_caja()
        metodo_sin = self.env['pos.payment.method'].create({
            'name': 'Getnet sin terminal',
            'use_payment_terminal': 'getnet',
            'getnet_provider_id': self.provider.id,
        })
        with self.assertRaises(UserError):
            metodo_sin._getnet_terminal()

    def test_cierre_de_caja_solo_mira_las_terminales_de_esa_caja(self):
        """
        El cierre de una caja no puede arrastrar el pinpad de la otra:
        cerraría su lote a mitad del turno y sus transacciones en vuelo
        bloquearían este cierre.
        """
        terminal2, _metodo2, session2 = self._segunda_caja()
        self.assertEqual(self.session._getnet_terminales(), self.terminal)
        self.assertEqual(session2._getnet_terminales(), terminal2)
