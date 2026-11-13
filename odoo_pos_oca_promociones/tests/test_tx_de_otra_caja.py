# -*- coding: utf-8 -*-
"""
Una orden nueva no se queda con la transacción OCA con promoción de otra caja (Forum, 2026-11-12).

El ``create`` de ``pos.order`` buscaba transacciones con promoción sin orden en toda la base, sin
filtrar por sesión ni caja, y si la orden no tenía un pago que apuntara a una tomaba «la más
reciente de los últimos 5 minutos». En el ``create`` la orden todavía no tiene pagos, así que
siempre caía en ese recurso: la orden 50756 (San Martín, efectivo $299) se quedó con la tx 35299
de Colonia ($2.075,19, 20 % Surf) e imprimió su voucher. 34 casos desde el 1-10.

Ahora sólo se liga la transacción a la que apunta un pago OCA de la propia orden.
"""
import json

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTxDeOtraCaja(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test otra caja)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, metodo_oca.ids)],
        })
        cls.descuento = cls.env['product.product'].create({
            'name': 'Descuento (test otra caja)', 'type': 'service',
        })
        cls.promocion = cls.env['payment.method.promotion'].create({
            'name': 'Descuento 20% - OCA (test otra caja)', 'payment_provider_id': cls.proveedor.id,
            'discount_product_id': cls.descuento.id, 'discount_percent': 20.0,
        })
        cls.prenda = cls.env['product.product'].create({
            'name': 'Remera (test otra caja)', 'list_price': 299.0,
        })
        cls.metodo_oca = cls.env['pos.payment.method'].create({
            'name': 'OCA (test otra caja)', 'use_payment_terminal': 'oca',
            'payment_provider': cls.proveedor.id,
        })
        # Caja que cobra en efectivo (San Martín) y caja que cobró con tarjeta (Colonia).
        cls.caja_efectivo = cls.env['pos.config'].create({'name': 'Caja efectivo (test otra caja)'})
        cls.caja_efectivo.open_ui()
        cls.sesion_efectivo = cls.caja_efectivo.current_session_id
        cls.caja_tarjeta = cls.env['pos.config'].create({'name': 'Caja tarjeta (test otra caja)'})
        cls.caja_tarjeta.payment_method_ids |= cls.metodo_oca
        cls.caja_tarjeta.open_ui()
        cls.sesion_tarjeta = cls.caja_tarjeta.current_session_id

    def _tx_con_promocion(self, transaction_id, monto=2075.19):
        """Transacción del pinpad recién confirmada con promoción, todavía sin orden."""
        respuesta = {'promotion_info': {
            'is_promotion': True, 'discount_amount': 518.8, 'product_id': self.descuento.id,
            'description': self.promocion.name, 'promotion_id': self.promocion.id,
        }}
        return self.env['payment.transaction'].sudo().create({
            'amount': monto, 'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'payment_method_id': self.proveedor.payment_method_ids[:1].id,
            'provider_id': self.proveedor.id, 'reference': 'TEST-OTRA-CAJA-%s' % transaction_id,
            'oca_transaction_id': transaction_id, 'state': 'done',
            'is_promotion': True, 'oca_promotion_id': self.promocion.id,
            'oca_complete_response': json.dumps(respuesta),
        })

    def _orden(self, sesion, pagos=()):
        precio = self.prenda.list_price
        return self.env['pos.order'].create({
            'session_id': sesion.id,
            'lines': [(0, 0, {
                'product_id': self.prenda.id, 'qty': 1, 'price_unit': precio,
                'price_subtotal': precio, 'price_subtotal_incl': precio,
                'full_product_name': self.prenda.name,
            })],
            'payment_ids': [(0, 0, pago) for pago in pagos],
            'amount_total': precio, 'amount_tax': 0.0, 'amount_paid': 0.0, 'amount_return': 0.0,
        })

    def test_una_venta_en_efectivo_no_se_queda_con_la_tx_de_otra_caja(self):
        tx = self._tx_con_promocion('2631640141197764')
        orden = self._orden(self.sesion_efectivo)
        self.assertFalse(tx.pos_order_id, 'La venta en efectivo se quedó con la tarjeta de otra caja.')
        self.assertFalse(
            self.env['pos.order']._find_all_payment_transactions_for_pos_receipt(orden),
            'La venta en efectivo imprimiría el voucher de otra caja.',
        )

    def test_la_orden_cuyo_pago_apunta_a_la_tx_se_queda_con_ella(self):
        tx = self._tx_con_promocion('2631640141197765')
        orden = self._orden(self.sesion_tarjeta, pagos=[{
            'payment_method_id': self.metodo_oca.id, 'amount': 2075.19,
            'transaction_id': tx.oca_transaction_id,
        }])
        self.assertEqual(tx.pos_order_id, orden)
        self.assertEqual(tx.pos_payment_id, orden.payment_ids)
        self.assertEqual(orden.payment_ids.payment_transaction_id, tx)

    def test_no_se_roba_una_tx_que_ya_es_de_otra_orden(self):
        tx = self._tx_con_promocion('2631640141197766')
        duena = self._orden(self.sesion_tarjeta)
        tx.pos_order_id = duena
        self._orden(self.sesion_tarjeta, pagos=[{
            'payment_method_id': self.metodo_oca.id, 'amount': 2075.19,
            'transaction_id': tx.oca_transaction_id,
        }])
        self.assertEqual(tx.pos_order_id, duena)
