# -*- coding: utf-8 -*-
"""
Una factura que falla por SQL no se lleva la orden del PDV (Forum, 2026-11-12).

Con un cobro OCA aprobado, ``_generate_pos_order_invoice`` atrapa el error para que la orden
quede pagada sin factura. Pero lo atrapaba sin savepoint: un error de SQL (la línea de redondeo
sin cuenta) deja abortada la transacción de PostgreSQL, todo lo que sigue falla con «current
transaction is aborted» y la sincronización entera se pierde. 12 órdenes el 12 y 13-11.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_oca.models.pos_order import PosOrder as PosOrderOca


@tagged('post_install', '-at_install')
class TestFacturaFallidaSavepoint(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test savepoint)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, metodo_oca.ids)],
        })
        cls.prenda = cls.env['product.product'].create({
            'name': 'Remera (test savepoint)', 'list_price': 2075.2,
        })
        cls.config = cls.env['pos.config'].create({'name': 'Caja (test savepoint)'})
        cls.config.open_ui()
        cls.sesion = cls.config.current_session_id

    def _orden_cobrada_con_oca(self):
        precio = self.prenda.list_price
        orden = self.env['pos.order'].create({
            'session_id': self.sesion.id, 'to_invoice': True,
            'lines': [(0, 0, {
                'product_id': self.prenda.id, 'qty': 1, 'price_unit': precio,
                'price_subtotal': precio, 'price_subtotal_incl': precio,
                'full_product_name': self.prenda.name,
            })],
            'amount_total': precio, 'amount_tax': 0.0, 'amount_paid': precio, 'amount_return': 0.0,
        })
        self.env['payment.transaction'].sudo().create({
            'amount': precio, 'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'payment_method_id': self.proveedor.payment_method_ids[:1].id,
            'provider_id': self.proveedor.id, 'reference': 'TEST-SAVEPOINT-%s' % orden.id,
            'state': 'done', 'pos_order_id': orden.id,
        })
        return orden

    def _siguiente_en_la_cadena(self, orden):
        """Clase que sigue a odoo_pos_oca en el MRO y redefine _generate_pos_order_invoice."""
        mro = type(orden).__mro__
        desde = mro.index(PosOrderOca) + 1
        return next(c for c in mro[desde:] if '_generate_pos_order_invoice' in vars(c))

    def test_un_error_de_sql_en_la_factura_no_aborta_la_transaccion(self):
        orden = self._orden_cobrada_con_oca()

        def factura_que_revienta(registro):
            # Lo mismo que hace la restricción de la línea de redondeo: un error de PostgreSQL.
            registro.env.cr.execute("SELECT 1 / 0")

        with patch.object(self._siguiente_en_la_cadena(orden), '_generate_pos_order_invoice',
                          factura_que_revienta), \
                self.assertLogs('odoo.addons.odoo_pos_oca.models.pos_order', level='ERROR'):
            orden._generate_pos_order_invoice()

        # La transacción sigue viva: la sincronización puede terminar y la orden se guarda.
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone(), (1,))
        self.assertFalse(orden.to_invoice)
