# -*- coding: utf-8 -*-
"""
Post-proceso de las transacciones OCA del PDV (Forum, 2026-10-03).

En producción el cron «payment: post-process transactions» fallaba con cada
transacción OCA aprobada («The POS online payment (tx.id=N) could not be saved
correctly») y la reintentaba en cada corrida: más de 22.000 errores en un día y
un cron de 47 a 74 s, creciendo con cada venta.
"""
from unittest import SkipTest
from unittest.mock import patch

from odoo.addons.pos_online_payment.models.payment_transaction import (
    PaymentTransaction as PosOnlinePaymentTx,
)
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPostProcesoOca(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tx = cls.env['payment.transaction'].sudo()
        cls.pedido = cls.env['pos.order'].sudo().search(
            [('state', 'in', ('paid', 'done', 'invoiced')), ('amount_total', '>', 0)],
            order='id desc', limit=1,
        )
        if not cls.pedido:
            raise SkipTest('la base no tiene ventas del PDV para asociar')
        respuesta = {'ResponseCode': '0', 'TransactionId': 'TXTEST-POSTPROC',
                     'TotalAmount': '10000', 'Currency': '858', 'Issuer': '21',
                     'Ticket': '1', 'Batch': '1'}
        cls.tx = cls.Tx.create_oca_transaction_with_complete_data(
            respuesta, transaction_id='TXTEST-POSTPROC',
        )
        # Así queda una transacción del PDV cuando la venta se asocia.
        cls.tx.write({'pos_order_id': cls.pedido.id, 'state': 'done',
                      'is_post_processed': False})

    def test_sale_de_la_lista_del_cron(self):
        """El cron toma done + no post-procesadas: después de procesarla, ya no entra.

        No se llama a _cron_finalize_post_processing: hace cr.commit() y dentro
        de un test escribiría de verdad en la base.
        """
        dominio = [('id', '=', self.tx.id), ('state', '=', 'done'), ('is_post_processed', '=', False)]
        self.assertTrue(self.Tx.search(dominio))
        self.tx._finalize_post_processing()
        self.assertFalse(self.Tx.search(dominio))

    def test_queda_post_procesada_sin_error(self):
        self.tx._finalize_post_processing()
        self.assertTrue(self.tx.is_post_processed)

    def test_no_agrega_un_pago_extra_a_la_venta(self):
        pagos_antes = self.pedido.payment_ids
        self.tx._finalize_post_processing()
        self.assertEqual(self.pedido.payment_ids, pagos_antes)
        self.assertFalse(self.tx.payment_id, 'no se crea account.payment para un cobro del PDV')

    def test_el_estandar_sigue_para_otros_proveedores(self):
        """A pos_online_payment le llegan sólo las transacciones que no son OCA."""
        otro = self.env['payment.provider'].sudo().search([('code', '!=', 'oca')], limit=1)
        if not otro:
            self.skipTest('la base no tiene proveedores que no sean OCA')
        ajena = self.tx.copy({'reference': 'TXTEST-OTRO-PROV', 'provider_id': otro.id})
        recibidas = []

        def espia(recs):
            recibidas.append(recs)

        with patch.object(PosOnlinePaymentTx, '_process_pos_online_payment', espia):
            (self.tx | ajena)._process_pos_online_payment()
        self.assertEqual(len(recibidas), 1)
        self.assertEqual(recibidas[0], ajena)
