# -*- coding: utf-8 -*-
"""Puntos de lealtad en la reimpresión del ticket (Forum, 2026-11-20).

Al reimprimir, el ticket tomaba los puntos de la orden viva de la caja —otra— y no salían. Los
puntos de la venta salen del seguimiento de `loyalty.card.points`, que Odoo registra en la misma
transacción que la orden.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPuntosReimpresion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cliente = cls.env['res.partner'].create({'name': 'Cliente puntos (test)'})
        cls.programa = cls.env['loyalty.program'].create({
            'name': 'Puntos (test reimpresión)', 'program_type': 'loyalty',
        })
        cls.config = cls.env['pos.config'].create({'name': 'Caja (test puntos)'})
        cls.config.open_ui()

    def _orden(self, monto=1800.0, cliente=True):
        return self.env['pos.order'].create({
            'session_id': self.config.current_session_id.id,
            'partner_id': self.cliente.id if cliente else False,
            'amount_total': monto, 'amount_tax': 0.0, 'amount_paid': monto, 'amount_return': 0.0,
        })

    def _tarjeta(self, antes, despues):
        """La venta mueve el saldo de la tarjeta; el seguimiento se escribe al cerrar la
        transacción (precommit), con la misma create_date que la orden."""
        tarjeta = self.env['loyalty.card'].create({
            'program_id': self.programa.id, 'partner_id': self.cliente.id, 'points': antes,
        })
        self.env.flush_all()
        self.env.cr.precommit.run()
        tarjeta.points = despues
        self.env.flush_all()
        self.env.cr.precommit.run()
        return tarjeta

    def test_venta_trae_saldo_antes_y_despues(self):
        """Validación, Shop/1414: la tarjeta pasó de 216 a 234."""
        orden = self._orden()
        tarjeta = self._tarjeta(216, 234)
        puntos = orden._forum_puntos_del_ticket()
        self.assertEqual(puntos['card_id'], tarjeta.id)
        self.assertEqual((puntos['antes'], puntos['despues'], puntos['generados']), (216, 234, 18))
        self.assertEqual(puntos['canjeados'], 0)
        self.assertFalse(puntos['es_devolucion'])

    def test_devolucion(self):
        orden = self._orden(monto=-1800.0)
        self._tarjeta(234, 216)
        puntos = orden._forum_puntos_del_ticket()
        self.assertTrue(puntos['es_devolucion'])
        self.assertEqual((puntos['antes'], puntos['despues']), (234, 216))

    def test_sin_cliente_no_hay_puntos(self):
        orden = self._orden(cliente=False)
        self._tarjeta(216, 234)
        self.assertEqual(orden._forum_puntos_del_ticket(), {})

    def test_cambio_de_saldo_de_otra_venta_no_cuenta(self):
        """Sólo el cambio registrado junto con esta orden; no el de otra venta del cliente."""
        orden = self._orden()
        self._tarjeta(216, 234)
        self.env.cr.execute("UPDATE pos_order SET create_date = create_date - interval '1 day' WHERE id = %s",
                            (orden.id,))
        orden.invalidate_recordset(['create_date'])
        self.assertEqual(orden._forum_puntos_del_ticket(), {})

    def test_viaja_en_los_datos_del_ticket(self):
        orden = self._orden()
        self._tarjeta(216, 234)
        datos = self.env['pos.order'].get_receipt_data_from_invoice_or_order(
            [], False, orden.pos_reference or orden.name, orden.id)
        self.assertEqual(datos['reprint_loyalty']['despues'], 234)
        self.assertEqual(datos['reprint_loyalty']['generados'], 18)
