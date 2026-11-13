# -*- coding: utf-8 -*-
"""
Anular / devolver un cobro OCA desde la transacción (Forum, 2026-11-14).

Cobros aprobados que nunca quedaron en una venta (Paso Molino, 3 × 2.687,35): la
devolución del PDV necesita la venta y la contable un pago, así que no había por
dónde devolverlos. Se anula por ticket y, si el lote cerró (RC 109/110), se devuelve.
"""
import json
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.odoo_pos_oca_core.models import oca_utils

PEDIDO_CAJA = {
    'PosID': '30747668', 'SystemId': 'SYS-CAJA', 'Branch': '18', 'ClientAppId': '2',
    'UserId': '117', 'TransactionDateTimeyyyyMMddHHmmssSSS': '20261112154614917',
    'Amount': '335920', 'Currency': '858', 'InvoiceNumber': '0040010',
}
RESPUESTA_COMPRA = {
    'ResponseCode': '0', 'PosResponseCode': '00', 'TransactionType': 'C',
    'TotalAmount': '268735', 'Currency': '858', 'InvoiceNumber': '0040010', 'Ticket': '654',
}


@tagged('post_install', '-at_install')
class TestOcaReverso(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test reverso)', 'code': 'oca', 'state': 'test',
            'url_webservice': 'https://oca.test/itdServer', 'codigo_sistema': 'SYS-PROV',
            'branch': '1', 'client_app_id': '1',
            'payment_method_ids': [(6, 0, metodo.ids)],
        })
        cls.metodo = metodo
        cls.contador = new_test_user(
            cls.env, login='contador_reverso', groups='account.group_account_manager',
        )
        cls.cajero = new_test_user(cls.env, login='cajero_reverso', groups='base.group_user')

    def _cobro(self, **extra):
        vals = {
            'amount': 2687.35, 'currency_id': self.env.ref('base.UYU').id
            if self.env.ref('base.UYU', raise_if_not_found=False) else self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'payment_method_id': self.metodo.id, 'provider_id': self.proveedor.id,
            'reference': 'TEST-REVERSO-%s' % len(self.env['payment.transaction'].search([])),
            'state': 'done', 'pos_id': '30747668', 'ticket_number': '654', 'acquirer': '5',
            'oca_transaction_id': 'TID-ORIGINAL',
            'oca_complete_request': json.dumps(PEDIDO_CAJA),
            'oca_complete_response': json.dumps(RESPUESTA_COMPRA),
        }
        vals.update(extra)
        return self.env['payment.transaction'].sudo().create(vals)

    def _ejecutar(self, tx, respuestas):
        """Corre el reverso como contador con la API de OCA simulada; devuelve las llamadas."""
        llamadas = []

        def post(url, path, data, label, **kw):
            llamadas.append((path, dict(data)))
            return url, respuestas.pop(0)

        Prov = type(self.proveedor)
        with patch.object(oca_utils, 'oca_pos_http_post', side_effect=post), \
                patch.object(Prov, '_oca_lanzar_seguimiento_reverso') as hilo:
            resultado = tx.with_user(self.contador)._oca_ejecutar_reverso('cobro repetido')
        return resultado, llamadas, hilo

    def test_lote_abierto_anula_por_ticket_con_los_datos_de_la_caja(self):
        tx = self._cobro()
        resultado, llamadas, hilo = self._ejecutar(tx, [{'ResponseCode': '0', 'TransactionId': 'TID-ANUL'}])
        self.assertTrue(resultado['ok'])
        self.assertEqual(resultado['operacion'], 'anulacion')
        self.assertEqual(len(llamadas), 1)
        path, data = llamadas[0]
        self.assertEqual(path, '/processFinancialPurchaseVoidByTicket')
        self.assertEqual(data['TicketNumber'], '654')
        self.assertEqual(data['PosID'], '30747668')
        # Sucursal y sistema de la caja que cobró, no los del proveedor.
        self.assertEqual((data['SystemId'], data['Branch'], data['ClientAppId']), ('SYS-CAJA', '18', '2'))
        hilo.assert_called_once()
        self.assertTrue(tx.oca_reverso_en_curso_desde)
        self.assertEqual(tx.oca_reverso_motivo, 'cobro repetido')
        self.assertFalse(tx.oca_puede_revertir, 'con el candado puesto no se puede mandar otra')

    def test_lote_cerrado_pasa_a_devolucion(self):
        for rc in ('109', '110'):
            tx = self._cobro(oca_transaction_id='TID-%s' % rc)
            resultado, llamadas, hilo = self._ejecutar(tx, [
                {'ResponseCode': rc}, {'ResponseCode': '0', 'TransactionId': 'TID-DEV'},
            ])
            self.assertEqual(resultado['operacion'], 'devolucion')
            self.assertEqual([p for p, _d in llamadas],
                             ['/processFinancialPurchaseVoidByTicket', '/processFinancialPurchaseRefund'])
            devolucion = llamadas[1][1]
            self.assertEqual(devolucion['Amount'], '268735')
            self.assertEqual(devolucion['TicketNumber'], '654')
            self.assertEqual(devolucion['InvoiceNumber'], '0040010')
            # Fecha de la caja (hora local), no la de create_date en UTC.
            self.assertEqual(devolucion['OriginalTransactionDateyyMMdd'], '261112')
            self.assertEqual((devolucion['SystemId'], devolucion['Branch']), ('SYS-CAJA', '18'))
            hilo.assert_called_once()

    def test_terminal_rechaza_no_deja_candado(self):
        tx = self._cobro()
        with self.assertRaises(UserError):
            self._ejecutar(tx, [{'ResponseCode': '103', 'msg': 'Pinpad en uso'}])
        self.assertFalse(tx.oca_reverso_en_curso_desde)

    def test_sin_permiso_de_contabilidad(self):
        tx = self._cobro()
        with self.assertRaises(AccessError):
            tx.with_user(self.cajero).action_oca_anular_devolver()

    def test_no_se_revierte_lo_que_no_corresponde(self):
        casos = {
            'no aprobado': self._cobro(state='error', oca_transaction_id='T1'),
            'es una anulación': self._cobro(
                oca_transaction_id='T2',
                oca_complete_response=json.dumps(dict(RESPUESTA_COMPRA, TransactionType='A'))),
            'sin ticket': self._cobro(ticket_number=False, oca_transaction_id='T3'),
        }
        for nombre, tx in casos.items():
            with self.subTest(nombre):
                self.assertTrue(tx._oca_motivo_no_revertible())
                with self.assertRaises(UserError):
                    tx.with_user(self.contador).action_oca_anular_devolver()

    def test_registrar_resultado_liga_la_anulacion_y_suelta_el_candado(self):
        tx = self._cobro()
        self._ejecutar(tx, [{'ResponseCode': '0', 'TransactionId': 'TID-ANUL'}])
        respuesta = {
            'ResponseCode': '0', 'PosResponseCode': '00', 'TransactionType': 'A',
            'Ticket': '700', 'PosID': '30747668',
        }
        nueva = tx._oca_registrar_reverso('TID-ANUL', respuesta, {'PosID': '30747668'}, 'anulacion')
        self.assertEqual(nueva.oca_reverso_de_id, tx)
        self.assertEqual(nueva.oca_operacion_reverso, 'anulacion')
        self.assertEqual(nueva.state, 'done')
        self.assertAlmostEqual(nueva.amount, 2687.35, msg='sin TotalAmount, el monto es el del cobro')
        self.assertFalse(tx.oca_reverso_en_curso_desde)
        self.assertIn(nueva, tx.oca_reverso_ids)
        self.assertEqual(tx._oca_motivo_no_revertible(), 'Este cobro ya fue anulado o devuelto.')
        self.assertFalse(nueva.oca_puede_revertir, 'una anulación no se anula')

    def test_dialogo_manda_y_avisa(self):
        tx = self._cobro()
        accion = tx.with_user(self.contador).action_oca_anular_devolver()
        self.assertEqual(accion['res_model'], 'oca.reverso.wizard')
        wizard = self.env['oca.reverso.wizard'].with_user(self.contador).with_context(
            accion['context']).create({'motivo': 'helpdesk 3478'})
        Prov = type(self.proveedor)
        with patch.object(oca_utils, 'oca_pos_http_post',
                          return_value=('u', {'ResponseCode': '0', 'TransactionId': 'TID-W'})), \
                patch.object(Prov, '_oca_lanzar_seguimiento_reverso'):
            aviso = wizard.action_confirmar()
        self.assertEqual(aviso['tag'], 'display_notification')
        self.assertEqual(tx.oca_reverso_motivo, 'helpdesk 3478')
