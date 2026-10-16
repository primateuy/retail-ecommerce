# -*- coding: utf-8 -*-
"""
Cuotas de la confirmación con promoción OCA (Forum, 2026-10-16).

Al pasar la tarjeta el pinpad todavía no informa cuotas, y la caja inicia el cobro con 0. La
confirmación con descuento completaba con 1 y OCA aprobaba en 1 cuota aunque el cliente eligiera 6.
Ahora va 0, como en la confirmación sin promoción, y OCA toma las cuotas del pinpad.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCuotasConfirmacion(TransactionCase):

    def _cuotas(self, result, data):
        return self.env['pos.payment.method']._oca_promo_confirm_quotas(result, data)

    def test_sin_cuotas_informadas_deja_elegir_al_pinpad(self):
        # Respuesta real del pinpad al leer la tarjeta (RC 12) y cobro iniciado desde la caja.
        result = {'Acquirer': 5, 'Issuer': 21, 'ResponseCode': '12', 'TaxRefund': '0'}
        data = {'Quotas': '0', 'Installments': '0'}
        self.assertEqual(self._cuotas(result, data), 0)

    def test_respeta_las_cuotas_que_informa_el_pinpad(self):
        self.assertEqual(self._cuotas({'Quota': '6'}, {'Quotas': '0', 'Installments': '0'}), 6)

    def test_respeta_las_cuotas_del_cobro_inicial(self):
        self.assertEqual(self._cuotas({}, {'Quotas': '0', 'Installments': '3'}), 3)

    def test_valores_invalidos_no_fuerzan_una_cuota(self):
        self.assertEqual(self._cuotas({'Quota': 'null'}, {'Quotas': '', 'Installments': None}), 0)
