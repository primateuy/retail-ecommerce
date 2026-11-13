# -*- coding: utf-8 -*-
"""
El cobro con promoción OCA y la orden suman lo mismo, al centavo (Forum, 2026-11-12).

2594 con 20 %: 2594 - 518,8000000000001 = 2075,1999…; el ``int()`` lo truncaba a 207519 y el
pinpad cobraba 2075,19 mientras la orden sumaba 2075,20. Ese centavo dejaba en la factura una
línea de redondeo sin cuenta (las cajas redondean sólo con efectivo), la restricción
``account_move_line_check_accountable_required_fields`` saltaba y la orden no se guardaba.
12 órdenes el 12 y 13-11.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCentavoPromocion(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Metodo = self.env['pos.payment.method']

    def test_el_monto_con_descuento_no_pierde_el_centavo(self):
        descuento, monto = self.Metodo._oca_promo_descuento_y_monto(2594.0, 2594.0, 20.0)
        self.assertEqual(descuento, 518.8)
        self.assertEqual(monto, 2075.2)
        self.assertEqual(self.Metodo._oca_promo_centavos(monto), 207520)

    def test_el_codigo_viejo_truncaba(self):
        """Fija el caso real: el cálculo anterior daba 207519."""
        self.assertEqual(int((2594.0 - 2594.0 * 0.2) * 100), 207519)

    def test_montos_de_la_base_con_19_centavos(self):
        # Cobros reales con 20 % que quedaron en ,19 (2199,19 / 2191,19 / 2431,19 / 2239,19).
        for original, esperado in ((2594.0, 207520), (2749.0, 219920), (2739.0, 219120),
                                   (3039.0, 243120), (2799.0, 223920)):
            _descuento, monto = self.Metodo._oca_promo_descuento_y_monto(original, original, 20.0)
            self.assertEqual(self.Metodo._oca_promo_centavos(monto), esperado, original)

    def test_descuento_sobre_neto_tambien_va_en_centavos(self):
        descuento, monto = self.Metodo._oca_promo_descuento_y_monto(2594.0, 2126.2295, 20.0)
        self.assertEqual(descuento, 425.25)
        self.assertEqual(monto, 2168.75)

    def test_centavos_redondea_no_trunca(self):
        self.assertEqual(self.Metodo._oca_promo_centavos(2075.1999999999998), 207520)
        self.assertEqual(self.Metodo._oca_promo_centavos(1700.9699999), 170097)
