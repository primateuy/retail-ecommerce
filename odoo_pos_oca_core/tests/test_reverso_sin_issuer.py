# -*- coding: utf-8 -*-
"""
Reversos OCA que no quedaban registrados (Forum, 2026-10-02).

Cuando Odoo revierte un cobro por timeout (o por promoción incompatible), la
respuesta que persiste no trae ``Issuer``: ``_get_issuer_name`` hacía
``int(None)``, la creación de la ``payment.transaction`` se caía y el reverso
sólo quedaba en el log. En producción fueron 138 reversos en dos días, ninguno
en la base.

Además la respuesta del reverso no trae ``TotalAmount`` ni ``Currency``: el
monto y la moneda salen del request original enviado al pinpad.
"""
import json

from odoo.tests import TransactionCase, tagged


# Respuesta armada por el bucle de odoo_pos_oca_promociones al vencer el
# timeout propio, tal como quedó en el log de producción (tx 2627456110155585).
RESPUESTA_TIMEOUT = {
    'ResponseCode': '11',
    'msg': 'Tiempo de transacción excedido, envíe datos nuevamente.',
    'TransactionId': 2627456110155585,
    'RemainingExpirationTime': 0.0,
    'timeout_error': True,
    'reverse_processed': True,
    'reverse_success': True,
    'reverse_msg': 'Reversión procesada exitosamente',
}

# Request de la venta que se revirtió (mismo caso del log).
PEDIDO = {
    'Amount': '39900',
    'Currency': '858',
    'InvoiceNumber': '1',
    'PosID': '22224597',
    'TaxableAmount': '32705',
}


@tagged('post_install', '-at_install')
class TestReversoSinIssuer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tx = cls.env['payment.transaction'].sudo()

    def _crear(self, respuesta, pedido=PEDIDO, tid='TXTEST-REVERSO'):
        return self.Tx.create_oca_transaction_with_complete_data(
            dict(respuesta), transaction_id=tid, pos_data=dict(pedido) if pedido else None,
        )

    def test_issuer_vacio_no_revienta(self):
        Tx = self.Tx
        self.assertEqual(Tx._get_issuer_name(None), '')
        self.assertEqual(Tx._get_issuer_name(False), '')
        self.assertEqual(Tx._get_issuer_name(''), '')
        self.assertEqual(Tx._get_issuer_name('abc'), 'abc')
        self.assertTrue(Tx._get_issuer_name(21))

    def test_reverso_por_timeout_queda_registrado(self):
        tx = self._crear(RESPUESTA_TIMEOUT)
        self.assertTrue(tx, 'el reverso tiene que quedar como transacción')
        self.assertEqual(tx.state, 'error')
        self.assertEqual(tx.oca_response_code, '11')
        self.assertTrue(json.loads(tx.oca_complete_response)['reverse_processed'])
        self.assertEqual(tx.issuer_name, '')

    def test_monto_y_moneda_salen_del_pedido(self):
        """Sin TotalAmount, el monto revertido es el del request: $399, no 0."""
        tx = self._crear(RESPUESTA_TIMEOUT)
        self.assertAlmostEqual(tx.amount, 399.0)
        self.assertEqual(tx.currency_id.name, 'UYU')

    def test_moneda_del_pedido_en_dolares(self):
        usd = self.env.ref('base.USD')
        if not usd.active:
            usd.active = True
        tx = self._crear(RESPUESTA_TIMEOUT, dict(PEDIDO, Currency='840'), tid='TXTEST-REVERSO-USD')
        self.assertEqual(tx.currency_id, usd)

    def test_sin_pedido_el_monto_sigue_en_cero(self):
        tx = self._crear(RESPUESTA_TIMEOUT, pedido=None, tid='TXTEST-REVERSO-SIN-PEDIDO')
        self.assertEqual(tx.amount, 0.0)

    def test_cobro_aprobado_usa_el_total_de_la_respuesta(self):
        """El respaldo no pisa el monto real cuando la respuesta lo trae."""
        aprobado = {'ResponseCode': '0', 'TransactionId': 'TXTEST-OK', 'PosID': '22224597',
                    'TotalAmount': '25000', 'Currency': '858', 'Issuer': '21'}
        tx = self._crear(aprobado, tid='TXTEST-OK')
        self.assertEqual(tx.state, 'done')
        self.assertAlmostEqual(tx.amount, 250.0)

    def test_reverso_por_promocion_incompatible(self):
        respuesta = {
            'ResponseCode': '999', 'TransactionId': 'TXTEST-PROMO',
            'msg': 'No se puede cobrar con la promoción de tarjeta',
            'promotion_incompatible_cancelled': True,
            'reverse_after_incompatible_ok': True, 'reverse_msg': 'Resultado OK',
        }
        tx = self._crear(respuesta, tid='TXTEST-PROMO')
        self.assertEqual(tx.state, 'error')
        self.assertAlmostEqual(tx.amount, 399.0)
