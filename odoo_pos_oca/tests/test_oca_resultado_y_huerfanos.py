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
        # Anularlo desde la transacción se puede, pero avisa que la venta queda cobrada.
        self.assertEqual(tx._oca_motivo_no_revertible(), '')
        self.assertIn('PDV', '\n'.join(tx._oca_advertencias_reverso()))
        # Crearle el pago contable también avisa: el ingreso quedaría dos veces.
        self.assertEqual(tx._oca_motivo_sin_pago_asociado(), '')
        self.assertIn('dos veces', '\n'.join(tx._oca_advertencias_pago_asociado()))

    # --- cobro registrado por el POS de respaldo (2026-11-20) ---

    def _pago_respaldo(self, autorizacion, monto=558.40):
        """Venta pasada por un método manual con la autorización del cobro del pinpad."""
        manual = self.env['pos.payment.method'].create({'name': 'POS Manual (test respaldo)'})
        config = self.env['pos.config'].create({'name': 'Caja (test respaldo)'})
        config.payment_method_ids = [(4, self.pm.id), (4, manual.id)]
        config.open_ui()
        orden = self.env['pos.order'].create({
            'session_id': config.current_session_id.id,
            'amount_total': monto, 'amount_tax': 0.0, 'amount_paid': monto, 'amount_return': 0.0,
        })
        pago = self.env['pos.payment'].create({
            'pos_order_id': orden.id, 'payment_method_id': manual.id, 'amount': monto,
        })
        proveedor_manual = self.env['payment.provider'].create({
            'name': 'Manual (test respaldo)', 'code': 'none', 'state': 'test',
        })
        tx_manual = self.env['payment.transaction'].sudo().create({
            'amount': monto, 'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'payment_method_id': self.metodo_oca.id, 'provider_id': proveedor_manual.id,
            'reference': 'TEST-RESPALDO-%s' % autorizacion, 'state': 'done',
            'pos_payment_id': pago.id, 'authorization_code': autorizacion,
        })
        return pago, tx_manual

    def test_cobro_registrado_por_respaldo_no_es_suelto(self):
        """Producción 19/20-11: 20 de 28 cobros «sin venta» ya estaban en una venta de respaldo."""
        tx = self._tx('TID-RESP', authorization_code='227244')
        pago, _manual = self._pago_respaldo('227244')
        self.assertEqual(tx.oca_respaldo_payment_id, pago)
        self.assertEqual(tx._oca_pago_pos_del_cobro(), pago)
        self.assertEqual(self.pm.oca_cobros_sin_venta(), [])

    def test_otra_autorizacion_no_lo_marca(self):
        tx = self._tx('TID-OTRA-AUT', authorization_code='111111')
        self._pago_respaldo('999999')
        self.assertFalse(tx.oca_respaldo_payment_id)
        self.assertEqual([c['id'] for c in self.pm.oca_cobros_sin_venta()], [tx.id])

    def test_respaldo_de_otra_terminal_no_lo_marca(self):
        tx = self._tx('TID-OTRA-TERM', authorization_code='333333', pos_id='OTRA')
        self._pago_respaldo('333333')
        self.assertFalse(tx.oca_respaldo_payment_id)

    def test_la_migracion_marca_los_anteriores(self):
        """Los respaldos que ya existían se marcan desde las transacciones manuales."""
        pago, manual = self._pago_respaldo('444444')
        tx = self._tx('TID-ANTERIOR', authorization_code='444444')
        tx.create_date = manual.create_date
        self.assertFalse(tx.oca_respaldo_payment_id)
        self.assertEqual(manual._oca_marcar_cobro_registrado_por_respaldo(), tx)
        self.assertEqual(tx.oca_respaldo_payment_id, pago)

    def test_dos_tarjetas_la_primera_no_es_suelta(self):
        """La primera tarjeta de la venta que se está cobrando todavía no tiene pago del PDV."""
        primera = self._tx('TID-TARJETA-1')
        self.assertEqual([c['id'] for c in self.pm.oca_cobros_sin_venta()], [primera.id])
        self.assertEqual(self.pm.oca_cobros_sin_venta(excluir_tids=['TID-TARJETA-1']), [])

    def test_menu_cobros_sin_venta_solo_con_su_grupo(self):
        """El menú lo ve sólo quien tenga el grupo, que no viene con nadie, ni el administrador."""
        grupo = self.env.ref('odoo_pos_oca.group_oca_cobros_sin_venta')
        menu = self.env.ref('odoo_pos_oca.menu_payment_transaction_oca_sin_venta')
        self.assertEqual(menu.groups_id, grupo)
        self.assertFalse(grupo.implied_ids)
        self.assertNotIn(grupo, self.env.ref('base.user_admin').groups_id)
