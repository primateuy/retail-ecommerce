# -*- coding: utf-8 -*-
"""
Impuesto de la línea de descuento de la promoción OCA (Forum, 2026-10-16).

La línea juntaba los impuestos de todas las demás líneas de la orden. Con una bolsa
(«Entrega Gratuita») el descuento quedaba con 22 % + Entrega Gratuita: dos indicadores de
facturación en una línea y el CFE no se podía emitir (`Expected singleton:
invoicing.indicator(3, 5)`). 145 órdenes el 15 y 16-10.

Ahora lleva el impuesto del producto de descuento. Si ese producto tiene más de uno, el cobro y la
venta siguen normal pero la factura queda en borrador, sin emitir, con el motivo en el chatter.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestImpuestoDescuento(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Tax = cls.env['account.tax']
        cls.iva_basico = Tax.create({'name': 'Ventas 22% (test desc)', 'amount': 22.0,
                                     'type_tax_use': 'sale', 'price_include': True})
        cls.gratuita = Tax.create({'name': 'Entrega Gratuita (test desc)', 'amount': 0.0,
                                   'type_tax_use': 'sale', 'price_include': True})
        Product = cls.env['product.product']
        cls.prenda = Product.create({'name': 'Remera (test desc)', 'list_price': 1000.0,
                                     'taxes_id': [(6, 0, cls.iva_basico.ids)]})
        cls.bolsa = Product.create({'name': 'Bolsa TNT (test desc)', 'list_price': 0.0,
                                    'taxes_id': [(6, 0, cls.gratuita.ids)]})
        cls.descuento = Product.create({'name': 'Descuento (test desc)', 'type': 'service',
                                        'taxes_id': [(6, 0, cls.iva_basico.ids)]})
        metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test desc)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, metodo_oca.ids)],
        })
        cls.promocion = cls.env['payment.method.promotion'].create({
            'name': 'Descuento 20% - OCA (test desc)', 'payment_provider_id': proveedor.id,
            'discount_product_id': cls.descuento.id, 'discount_percent': 20.0,
        })
        cls.config = cls.env['pos.config'].create({'name': 'Caja (test desc)'})
        cls.config.open_ui()
        cls.session = cls.config.current_session_id

    def _orden(self, *productos):
        lineas = []
        for producto in productos:
            precio = producto.list_price
            lineas.append((0, 0, {
                'product_id': producto.id, 'qty': 1, 'price_unit': precio,
                'tax_ids': [(6, 0, producto.taxes_id.ids)],
                'price_subtotal': precio, 'price_subtotal_incl': precio,
                'full_product_name': producto.name,
            }))
        total = sum(p.list_price for p in productos)
        return self.env['pos.order'].create({
            'session_id': self.session.id, 'lines': lineas,
            'amount_total': total, 'amount_tax': 0.0, 'amount_paid': 0.0, 'amount_return': 0.0,
        })

    def _linea_descuento(self, orden):
        return orden.lines.filtered(lambda l: l.product_id == self.descuento)

    def test_con_bolsa_el_descuento_lleva_solo_el_impuesto_del_producto(self):
        orden = self._orden(self.prenda, self.bolsa)
        resultado = orden.add_promotion_discount_line(200.0, self.descuento.id, 'Descuento 20% - OCA')
        self.assertTrue(resultado['success'], resultado.get('error'))
        self.assertEqual(self._linea_descuento(orden).tax_ids, self.iva_basico)

    def test_sin_bolsa_queda_igual_que_antes(self):
        orden = self._orden(self.prenda)
        resultado = orden.add_promotion_discount_line(200.0, self.descuento.id, 'Descuento 20% - OCA')
        self.assertTrue(resultado['success'], resultado.get('error'))
        linea = self._linea_descuento(orden)
        self.assertEqual(linea.tax_ids, self.iva_basico)
        # Impuesto incluido: el descuento TTC va entero al precio, como antes.
        self.assertAlmostEqual(linea.price_unit, -200.0)
        self.assertAlmostEqual(linea.price_subtotal_incl, -200.0)

    def test_producto_de_descuento_con_dos_impuestos_no_corta_el_cobro(self):
        """El descuento se agrega igual (con los dos impuestos): la venta no se corta."""
        self.descuento.taxes_id = [(6, 0, (self.iva_basico | self.gratuita).ids)]
        orden = self._orden(self.prenda, self.bolsa)
        resultado = orden.add_promotion_discount_line(200.0, self.descuento.id, 'Descuento 20% - OCA')
        self.assertTrue(resultado['success'], resultado.get('error'))
        self.assertEqual(self._linea_descuento(orden).tax_ids, self.iva_basico | self.gratuita)

    def test_producto_de_descuento_con_dos_impuestos_deja_la_factura_sin_emitir(self):
        self.descuento.taxes_id = [(6, 0, (self.iva_basico | self.gratuita).ids)]
        orden = self._orden(self.prenda, self.bolsa)
        orden.partner_id = self.env['res.partner'].create({'name': 'Cliente (test desc)'})
        PosOrder = type(self.env['pos.order'])
        cobro_oca = (200.0, self.descuento.id, 'Descuento 20% - OCA', self.promocion.id)
        with patch.object(PosOrder, '_oca_promo_sync_payment_amounts_from_transactions', return_value=None), \
                patch.object(PosOrder, '_oca_promo_collect_discount_totals_from_payments', return_value=cobro_oca):
            orden._generate_pos_order_invoice()
        self.assertEqual(orden.state, 'invoiced')
        self.assertEqual(orden.account_move.state, 'draft')
        self.assertTrue(orden.account_move.invoice_line_ids.filtered(lambda l: l.product_id == self.descuento))
        self.assertIn('Factura sin emitir', orden.account_move.message_ids[:1].body)

    def test_con_un_solo_impuesto_no_marca_error(self):
        orden = self._orden(self.prenda, self.bolsa)
        orden.add_promotion_discount_line(200.0, self.descuento.id, 'Descuento 20% - OCA')
        self.assertFalse(orden._oca_promo_discount_tax_error())
