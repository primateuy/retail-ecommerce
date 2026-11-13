# -*- coding: utf-8 -*-
"""
El PDV no depende sólo del aviso por bus (Forum, 2026-11-13, Florida tx 37187).

El servidor aprobó el cobro y mandó el resultado sólo por el bus; la caja nunca lo
recibió, se recargó y se volvió a cobrar. La caja ahora consulta el resultado
guardado y, antes de cobrar, ve los cobros aprobados de su terminal sin venta.
"""
import json

from odoo.tests import TransactionCase, tagged

TERMINAL = 'T-FLORIDA'


@tagged('post_install', '-at_install')
class TestOcaResultadoYHuerfanos(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test huérfanos)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, cls.metodo_oca.ids)],
        })
        cls.pm = cls.env['pos.payment.method'].create({
            'name': 'OCA test huérfanos', 'use_payment_terminal': 'oca',
            'codigo_terminal': TERMINAL,
        })

    def _tx(self, tid, respuesta=None, **extra):
        vals = {
            'amount': 558.40, 'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'payment_method_id': self.metodo_oca.id, 'provider_id': self.proveedor.id,
            'reference': 'TEST-HUERF-%s' % tid, 'state': 'done', 'pos_id': TERMINAL,
            'ticket_number': '514', 'card_last_four': '0916', 'oca_transaction_id': tid,
            'oca_complete_response': json.dumps(respuesta or {
                'ResponseCode': '0', 'PosResponseCode': '00', 'TransactionType': 'C',
                'Ticket': '514', 'Acquirer': 5,
            }),
        }
        vals.update(extra)
        return self.env['payment.transaction'].sudo().create(vals)

    # --- consulta del resultado ---

    def test_sin_transaccion_queda_pendiente(self):
        self.assertEqual(self.pm.oca_consultar_resultado('NO-EXISTE'), {'pending': True})
        self.assertEqual(self.pm.oca_consultar_resultado(''), {'pending': True})

    def test_resultado_final_con_la_forma_del_bus(self):
        self._tx('TID-1')
        payload = self.pm.oca_consultar_resultado('TID-1')
        self.assertEqual(payload['ResponseCode'], '0')
        self.assertEqual(payload['PosResponseCode'], '00')
        self.assertEqual(payload['Ticket'], '514')
        self.assertEqual(payload['origin_transaction_id'], 'TID-1')

    def test_respuesta_intermedia_sigue_pendiente(self):
        self._tx('TID-2', respuesta={'ResponseCode': '12', 'Acquirer': 5})
        self.assertEqual(self.pm.oca_consultar_resultado('TID-2'), {'pending': True})

    def test_no_entrega_resultados_de_otra_terminal(self):
        self._tx('TID-3', pos_id='OTRA')
        self.assertEqual(self.pm.oca_consultar_resultado('TID-3'), {'pending': True})

    # --- cobros sin venta ---

    def test_cobro_aprobado_sin_venta_aparece(self):
        tx = self._tx('TID-H1')
        cobros = self.pm.oca_cobros_sin_venta()
        self.assertEqual([c['id'] for c in cobros], [tx.id])
        self.assertEqual(cobros[0]['ticket'], '514')
        self.assertEqual(cobros[0]['card_last_four'], '0916')

    def test_no_aparecen_los_que_no_son_huerfanos(self):
        self._tx('TID-E', state='error')
        self._tx('TID-O', pos_id='OTRA')
        self._tx('TID-A', respuesta={'ResponseCode': '0', 'PosResponseCode': '00', 'TransactionType': 'A'})
        original = self._tx('TID-ANULADO')
        self._tx('TID-LA-ANULACION', oca_reverso_de_id=original.id)
        self.assertEqual(self.pm.oca_cobros_sin_venta(), [])

    def test_el_pago_del_pdv_por_id_de_oca_lo_saca(self):
        """La asociación tx→pago a veces no se escribe (Treinta y Tres, tx 37645)."""
        tx = self._tx('TID-VENTA')
        config = self.env['pos.config'].create({'name': 'Caja (test huérfanos)'})
        config.open_ui()
        orden = self.env['pos.order'].create({
            'session_id': config.current_session_id.id,
            'amount_total': 558.40, 'amount_tax': 0.0, 'amount_paid': 558.40, 'amount_return': 0.0,
        })
        self.env['pos.payment'].create({
            'pos_order_id': orden.id, 'payment_method_id': config.payment_method_ids[:1].id,
            'amount': 558.40, 'transaction_id': 'TID-VENTA',
        })
        self.assertEqual(self.pm.oca_cobros_sin_venta(), [])
        # Y por la misma razón no se ofrece anularlo desde la transacción.
        self.assertIn('PDV', tx._oca_motivo_no_revertible())
