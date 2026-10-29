# -*- coding: utf-8 -*-
"""
Ley y número de factura en la confirmación OCA con promociones (Forum, 2026-10-29).

La confirmación no mandaba TaxRefund (el manual lo marca obligatorio) y mandaba como factura el
nombre de la orden, de más de 7 caracteres: OCA respondía «Sin Nro Factura No Aplica Ley».
Se verifica lo que efectivamente sale hacia OCA.
"""
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

RUTA_POST = 'odoo.addons.odoo_pos_oca_promociones.models.pos_payment_method.requests.post'


@tagged('post_install', '-at_install')
class TestLeyConfirmacion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo_pago = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        proveedor = cls.env['payment.provider'].create({
            'name': 'OCA confirmación (test)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, metodo_pago.ids)],
        })
        cls.metodo = cls.env['pos.payment.method'].create({
            'name': 'OCA confirmación (test)', 'use_payment_terminal': 'oca',
            'payment_provider': proveedor.id, 'url_webservice': 'https://oca.invalid/itdServer',
        })
        tipo_rut = cls.env['l10n_latam.identification.type'].create(
            {'name': 'RUT (test confirmación)', 'is_vat': True})
        cls.empresa = cls.env['res.partner'].create({
            'name': 'Empresa (test confirmación)',
            'l10n_latam_identification_type_id': tipo_rut.id,
        })

    def _confirmar(self, data):
        respuesta = MagicMock(status_code=200, text='{"ResponseCode": 0}')
        respuesta.json.return_value = {'ResponseCode': 0}
        with patch(RUTA_POST, return_value=respuesta) as post:
            self.metodo.processConfirmFinancialPurchase(data, False)
        return post.call_args.kwargs['json']

    def _confirmacion_de_la_caja(self, partner=None):
        """Como la arma confirmFinancialPurchaseWithoutPromotion."""
        return {
            'TransactionId': '2630138163113448', 'Amount': '420500', 'Plan': '0',
            'Currency': '858', 'TaxableAmount': '344671', 'InvoiceAmount': '420500',
            'OcaOrderReference': 'Orden 02038-001-0003',
            'OcaPartnerId': partner.id if partner else False,
        }

    def test_confirmacion_lleva_ley_y_factura(self):
        enviado = self._confirmar(self._confirmacion_de_la_caja())
        self.assertEqual(enviado['TaxRefund'], 1)
        self.assertEqual(enviado['InvoiceNumber'], '0010003')
        self.assertNotIn('OcaOrderReference', enviado)
        self.assertNotIn('OcaPartnerId', enviado)

    def test_confirmacion_con_rut_ley_0(self):
        enviado = self._confirmar(self._confirmacion_de_la_caja(self.empresa))
        self.assertEqual(enviado['TaxRefund'], 0)

    def test_confirmacion_del_backend_conserva_lo_del_cobro(self):
        """El hilo de segundo plano confirma con los datos del cobro, ya corregidos."""
        enviado = self._confirmar({'TransactionId': '1', 'Amount': '100', 'Currency': '858',
                                   'TaxRefund': 0, 'InvoiceNumber': '0010003'})
        self.assertEqual(enviado['TaxRefund'], 0)
        self.assertEqual(enviado['InvoiceNumber'], '0010003')

    def test_cobro_con_promociones_manda_ley_y_factura(self):
        """El cobro con promociones no pasa por el método base: también corrige los datos."""
        respuesta = MagicMock()
        respuesta.json.return_value = {'ResponseCode': 100}
        data = {'PosID': '1', 'Amount': '420500', 'Currency': '858', 'TaxRefund': '1',
                'InvoiceNumber': '1', 'OcaOrderReference': 'Orden 02038-001-0003',
                'OcaPartnerId': False}
        with patch(RUTA_POST, return_value=respuesta) as post, \
                patch('odoo.addons.odoo_pos_oca.models.pos_payment_method.requests.post',
                      return_value=respuesta) as post_base:
            self.metodo.processFinancialPurchase(data, self.env['pos.session'].search([], limit=1).id)
        llamada = post.call_args or post_base.call_args
        enviado = llamada.kwargs['json']
        self.assertEqual(enviado['InvoiceNumber'], '0010003')
        self.assertEqual(enviado['TaxRefund'], '1')
        self.assertNotIn('OcaOrderReference', enviado)
