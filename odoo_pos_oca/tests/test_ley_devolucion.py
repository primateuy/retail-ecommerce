# -*- coding: utf-8 -*-
"""
Ley de devolución de impuestos y número de factura de las ventas OCA (Forum, 2026-10-29).

Clientes reclamaron que no se les descontaban los puntos de IVA con débito. El PDV mandaba
TaxRefund 99 (no existe en el Anexo 3 de POSLink) y factura «1»; OCA respondía TaxRefund 0 e
imprimía «Sin Nro Factura No Aplica Ley». Fue así en las 18.222 ventas de octubre.

Ahora la ley sale del proveedor (0 si se factura con RUT) y la factura, de la referencia de la
orden: caja y secuencia, 7 caracteres.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_oca_core.models.oca_utils import (
    oca_invoice_number_from_reference,
    oca_partner_factura_con_rut,
)


@tagged('post_install', '-at_install')
class TestLeyDevolucion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo_pago = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA ley (test)', 'code': 'oca', 'state': 'test',
            'payment_method_ids': [(6, 0, metodo_pago.ids)],
        })
        cls.metodo = cls.env['pos.payment.method'].create({
            'name': 'OCA ley (test)',
            'use_payment_terminal': 'oca',
            'payment_provider': cls.proveedor.id,
        })
        Tipo = cls.env['l10n_latam.identification.type']
        cls.tipo_rut = Tipo.create({'name': 'RUT (test ley)', 'is_vat': True})
        cls.tipo_ci = Tipo.create({'name': 'CI (test ley)', 'is_vat': False})
        Partner = cls.env['res.partner']
        cls.consumidor = Partner.create({'name': 'Consumidor final (test ley)',
                                         'l10n_latam_identification_type_id': cls.tipo_ci.id})
        cls.empresa = Partner.create({'name': 'Empresa con RUT (test ley)',
                                      'l10n_latam_identification_type_id': cls.tipo_rut.id})

    def _venta(self, partner=None, referencia='Orden 02038-001-0003'):
        """Datos como los arma la caja."""
        return {
            'Amount': '420500', 'Currency': '858', 'TaxRefund': '1',
            'TaxableAmount': '344671', 'InvoiceAmount': '420500', 'InvoiceNumber': '1',
            'OcaOrderReference': referencia,
            'OcaPartnerId': partner.id if partner else False,
        }

    # Número de factura -------------------------------------------------

    def test_numero_desde_la_referencia(self):
        """La venta del reclamo: Minas, Orden 02038-001-0003."""
        self.assertEqual(oca_invoice_number_from_reference('Orden 02038-001-0003'), '0010003')
        self.assertEqual(oca_invoice_number_from_reference('Orden 00012-002-12345'), '0212345')
        self.assertEqual(oca_invoice_number_from_reference('Orden 00012-001-0007'), '0010007')
        self.assertIsNone(oca_invoice_number_from_reference(''))
        self.assertIsNone(oca_invoice_number_from_reference(None))

    def test_numero_de_7_caracteres_siempre(self):
        for ref in ('Orden 99999-999-99999999', 'Orden 1-1-1', 'PDV - SUCURSAL  MINAS/0587'):
            self.assertEqual(len(oca_invoice_number_from_reference(ref)), 7, ref)

    # Ley ---------------------------------------------------------------

    def test_consumidor_final_ley_19210(self):
        data = self.metodo._oca_aplicar_ley_y_factura(self._venta(self.consumidor))
        self.assertEqual(data['TaxRefund'], '1')
        self.assertEqual(data['InvoiceNumber'], '0010003')

    def test_sin_cliente_ley_19210(self):
        data = self.metodo._oca_aplicar_ley_y_factura(self._venta())
        self.assertEqual(data['TaxRefund'], '1')

    def test_cliente_con_rut_ley_0(self):
        """Manual POSLink: «TaxRefund para casos factura con RUT es 0»."""
        self.assertTrue(oca_partner_factura_con_rut(self.empresa))
        data = self.metodo._oca_aplicar_ley_y_factura(self._venta(self.empresa))
        self.assertEqual(data['TaxRefund'], '0')

    def test_rut_de_la_localizacion_uruguaya(self):
        """El «RUC» de Forum no tiene is_vat: se reconoce por check_type."""
        ruc = self.env.ref('l10n_uy_einvoice_base.dgi_document_type_ruc', raise_if_not_found=False)
        if not ruc:
            self.skipTest('Sin la localización uruguaya')
        empresa = self.env['res.partner'].create({
            'name': 'Empresa RUC (test ley)', 'l10n_latam_identification_type_id': ruc.id,
        })
        self.assertTrue(oca_partner_factura_con_rut(empresa))
        ci = self.env.ref('l10n_uy_einvoice_base.dgi_document_type_ci')
        self.assertFalse(oca_partner_factura_con_rut(
            self.env['res.partner'].create({'name': 'CI (test ley)',
                                            'l10n_latam_identification_type_id': ci.id})))

    def test_ley_configurada_en_el_proveedor(self):
        self.proveedor.oca_tax_refund_law = '4'
        data = self.metodo._oca_aplicar_ley_y_factura(self._venta(self.consumidor))
        self.assertEqual(data['TaxRefund'], '4')

    def test_proveedor_existente_queda_en_19210(self):
        self.assertEqual(self.proveedor.oca_tax_refund_law, '1')

    # Lo que va a OCA -----------------------------------------------------

    def test_los_datos_internos_no_van_a_oca(self):
        data = self.metodo._oca_aplicar_ley_y_factura(self._venta(self.consumidor))
        self.assertNotIn('OcaOrderReference', data)
        self.assertNotIn('OcaPartnerId', data)

    def test_segunda_pasada_no_cambia_nada(self):
        """El cobro con promociones pasa dos veces (su método y el base)."""
        data = self.metodo._oca_aplicar_ley_y_factura(self._venta(self.empresa))
        antes = dict(data)
        self.metodo._oca_aplicar_ley_y_factura(data)
        self.assertEqual(data, antes)
        self.assertEqual(data['TaxRefund'], '0')

    def test_el_99_viejo_se_reemplaza(self):
        """Datos sin referencia ni cliente (caja vieja en caché): no sale el 99."""
        data = {'TaxRefund': '99', 'InvoiceNumber': '1'}
        self.metodo._oca_aplicar_ley_y_factura(data)
        self.assertEqual(data['TaxRefund'], '1')

    def test_factura_larga_se_recorta(self):
        """La confirmación vieja mandaba el nombre de la orden (26 caracteres)."""
        data = {'TaxRefund': 1, 'InvoiceNumber': 'Orden 02038-001-0003'}
        self.metodo._oca_aplicar_ley_y_factura(data)
        self.assertEqual(data['InvoiceNumber'], '0010003')

    # Búsqueda de la orden ------------------------------------------------

    def test_la_orden_se_encuentra_por_el_numero_nuevo(self):
        orden = self.env['pos.order'].search(
            [('pos_reference', '=like', 'Orden %-%-%'), ('session_id', '!=', False)],
            order='id desc', limit=1,
        )
        if not orden:
            self.skipTest('Sin órdenes del PDV en la base')
        numero = oca_invoice_number_from_reference(orden.pos_reference)
        encontrada = self.metodo._find_related_pos_order_by_transaction_with_data(
            'TX-TEST-LEY', orden.session_id.id, {'InvoiceNumber': numero},
        )
        self.assertEqual(encontrada, orden)
