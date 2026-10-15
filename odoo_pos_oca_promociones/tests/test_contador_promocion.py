# -*- coding: utf-8 -*-
"""
Contador «Veces Aplicada» de las promociones OCA (Forum, 2026-10-15).

El hilo que espera al pinpad le sumaba 1 a la promoción y esa escritura recién salía al cerrar
su transacción, la misma que guarda el cobro y avisa a la caja. Todas las cajas usaban la misma
promoción: si otra la aplicó durante esos segundos, el UPDATE fallaba por concurrencia y se
deshacían el cobro y el aviso. OCA ya había cobrado y la pantalla quedaba esperando (4 casos el
15-10, entre ellos San José por $5.646,40).

Ahora la promoción queda en la transacción y el contador se cuenta desde ahí.
"""
import importlib.util
import json
import os
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContadorPromocion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test contador)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, metodo_oca.ids)],
        })
        cls.env['multiple.pos.config'].create({
            'name': 'Caja test contador', 'codigo_terminal': '90000077',
            'payment_provider_id': cls.proveedor.id,
        })
        producto = cls.env['product.product'].create({'name': 'Descuento OCA (test)', 'type': 'service'})
        Promocion = cls.env['payment.method.promotion']
        comunes = {'payment_provider_id': cls.proveedor.id, 'discount_product_id': producto.id,
                   'discount_percent': 20.0}
        cls.promo = Promocion.create(dict(comunes, name='Promo A (test)'))
        cls.otra_promo = Promocion.create(dict(comunes, name='Promo B (test)'))
        cls.Tx = cls.env['payment.transaction'].sudo()

    def _cobro(self, tid, promocion=None, codigo='0'):
        respuesta = {'ResponseCode': codigo, 'PosID': '90000077', 'TransactionId': tid,
                     'TotalAmount': '564640', 'Currency': '858', 'Issuer': '21',
                     'CardNumber': '542991******8034'}
        if promocion:
            respuesta['promotion_info'] = {'promotion_id': promocion.id, 'is_promotion': True,
                                           'discount_percent': 20.0}
        return self.Tx.create_oca_transaction_with_complete_data(
            respuesta, transaction_id=tid, pos_data={'PosID': '90000077', 'Amount': '705800'},
        )

    def test_la_transaccion_guarda_su_promocion(self):
        tx = self._cobro('TXTEST-CONT-1', self.promo)
        self.assertTrue(tx.is_promotion)
        self.assertEqual(tx.oca_promotion_id, self.promo)

    def test_aplicar_la_promocion_no_escribe_en_la_promocion(self):
        """Lo que chocaba entre cajas: el cobro no puede escribir en la promoción compartida."""
        Promocion = type(self.env['payment.method.promotion'])
        with patch.object(Promocion, 'write', side_effect=AssertionError('el cobro escribió en la promoción')):
            tx = self._cobro('TXTEST-CONT-2', self.promo)
            self.env.flush_all()
        self.assertEqual(tx.oca_promotion_id, self.promo)

    def test_el_contador_cuenta_los_cobros_aprobados_de_cada_promocion(self):
        self._cobro('TXTEST-CONT-3', self.promo)
        self._cobro('TXTEST-CONT-4', self.promo)
        self._cobro('TXTEST-CONT-5', self.otra_promo)
        self._cobro('TXTEST-CONT-6')
        rechazado = self._cobro('TXTEST-CONT-7', self.promo, codigo='5')
        self.assertNotEqual(rechazado.state, 'done')
        (self.promo | self.otra_promo).invalidate_recordset(['times_applied'])
        self.assertEqual(self.promo.times_applied, 2)
        self.assertEqual(self.otra_promo.times_applied, 1)

    def test_el_boton_abre_los_cobros_de_la_promocion(self):
        tx = self._cobro('TXTEST-CONT-8', self.promo)
        accion = self.promo.action_view_transactions()
        self.assertEqual(self.Tx.search(accion['domain']), tx)

    def test_la_migracion_vincula_las_transacciones_existentes(self):
        tx = self._cobro('TXTEST-CONT-9', self.promo)
        roto = self._cobro('TXTEST-CONT-10', self.promo)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE payment_transaction SET oca_promotion_id = NULL WHERE id IN %s",
            ((tx.id, roto.id),))
        self.env.cr.execute(
            "UPDATE payment_transaction SET oca_complete_response = %s WHERE id = %s",
            ('no es JSON promotion_id', roto.id))
        ruta = os.path.join(os.path.dirname(__file__), '..', 'migrations', '17.0.2.3.0', 'post-migration.py')
        spec = importlib.util.spec_from_file_location('migracion_contador', ruta)
        migracion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migracion)
        migracion.migrate(self.env.cr, '17.0.2.2.0')
        (tx | roto).invalidate_recordset(['oca_promotion_id'])
        self.assertEqual(tx.oca_promotion_id, self.promo)
        self.assertFalse(roto.oca_promotion_id)
        self.assertEqual(json.loads(tx.oca_complete_response)['promotion_info']['promotion_id'], self.promo.id)
