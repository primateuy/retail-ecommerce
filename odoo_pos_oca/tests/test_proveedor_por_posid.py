# -*- coding: utf-8 -*-
"""
Proveedor y empresa de las transacciones OCA del PDV (Forum, 2026-10-02).

Con un proveedor OCA por RUT, la transacción del PDV tomaba el primer
proveedor con ``code='oca'`` según el orden de ``payment.provider`` (estado,
secuencia, nombre). En Forum era el de Aweryl, y como la empresa de la
transacción es ``related`` del proveedor, las 327 transacciones de los PDV de
FORUM, Faringol, etc. quedaron en la empresa Aweryl.

Ahora el proveedor sale de la terminal del PosID, y las búsquedas que unen un
pago del PDV con su transacción aceptan cualquier proveedor OCA.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProveedorPorPosid(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Provider = cls.env['payment.provider']
        cls.metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.empresa_propia = cls.env.company
        cls.empresa_otra = cls.env['res.company'].create({'name': 'Otra RUT (test OCA)'})
        comunes = {'code': 'oca', 'state': 'test', 'sequence': 0,
                   'payment_method_ids': [(6, 0, cls.metodo_oca.ids)]}
        # «AAA» queda primero en el orden de payment.provider: es el que el
        # código viejo elegía para todas las transacciones, como Aweryl.
        cls.prov_otra = Provider.create(dict(comunes, name='AAA OCA otra RUT (test)',
                                             company_id=cls.empresa_otra.id))
        cls.prov_propia = Provider.create(dict(comunes, name='ZZZ OCA propia (test)',
                                               company_id=cls.empresa_propia.id))
        Terminal = cls.env['multiple.pos.config']
        Terminal.create({'name': 'Caja propia', 'codigo_terminal': '90000001',
                         'payment_provider_id': cls.prov_propia.id})
        Terminal.create({'name': 'Caja otra', 'codigo_terminal': '90000002',
                         'payment_provider_id': cls.prov_otra.id})
        cls.Tx = cls.env['payment.transaction'].sudo()

    def _crear_tx(self, pos_id, tid):
        respuesta = {'ResponseCode': '0', 'PosID': pos_id, 'TransactionId': tid,
                     'TotalAmount': '10000', 'Currency': '858', 'Issuer': '21'}
        pedido = {'PosID': pos_id, 'Amount': '10000', 'Currency': '858'}
        return self.Tx.create_oca_transaction_with_complete_data(
            respuesta, transaction_id=tid, pos_data=pedido,
        )

    def test_el_codigo_viejo_elegia_el_de_otra_rut(self):
        """Fija el escenario: el primero por orden es el proveedor de otra RUT."""
        primero = self.env['payment.provider'].sudo().search([('code', '=', 'oca')], limit=1)
        self.assertEqual(primero, self.prov_otra)

    def test_posid_de_la_caja_propia(self):
        tx = self._crear_tx('90000001', 'TXTEST-PROPIA')
        self.assertEqual(tx.provider_id, self.prov_propia)
        self.assertEqual(tx.company_id, self.empresa_propia)
        self.assertEqual(tx.payment_method_id, self.metodo_oca)

    def test_posid_de_la_caja_de_otra_rut(self):
        tx = self._crear_tx('90000002', 'TXTEST-OTRA')
        self.assertEqual(tx.provider_id, self.prov_otra)
        self.assertEqual(tx.company_id, self.empresa_otra)

    def test_posid_desconocido_usa_el_de_menor_id(self):
        """Respaldo fijo: el proveedor OCA de menor id, no el primero por nombre."""
        tx = self._crear_tx('11122299', 'TXTEST-DESCONOCIDO')
        menor = self.env['payment.provider'].sudo().search([('code', '=', 'oca')], order='id', limit=1)
        self.assertEqual(tx.provider_id, menor)
        self.assertNotEqual(tx.provider_id, self.prov_otra)

    def test_el_pago_del_pdv_se_une_con_tx_de_otro_proveedor(self):
        """La unión pago ↔ transacción no depende de cuál es el primer proveedor."""
        pago = self.env['pos.payment'].sudo().search(
            [('payment_method_id.use_payment_terminal', '=', 'oca')], order='id desc', limit=1,
        )
        if not pago:
            self.skipTest('La base no tiene pagos OCA del PDV para probar la unión')
        tx = self._crear_tx('90000001', 'TXTEST-UNION')
        self.assertNotEqual(tx.provider_id, self.prov_otra)
        pago.write({'transaction_id': 'TXTEST-UNION', 'payment_transaction_id': False})
        tx.pos_payment_id = False
        pago._associate_oca_transaction()
        self.assertEqual(pago.payment_transaction_id, tx)
        self.assertEqual(tx.pos_payment_id, pago)
