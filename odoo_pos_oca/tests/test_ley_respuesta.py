# -*- coding: utf-8 -*-
"""
Qué hace Odoo con la respuesta de OCA sobre la devolución de impuestos (Forum, 2026-10-29).

En la respuesta TaxRefund es la ley que OCA asocia a la tarjeta y TaxAmount lo que devolvió: la
ley se aplicó sólo si TaxAmount > 0. Hasta ahora el ticket del PDV imprimía siempre, fijo,
«Aplica dev. IVA-Ley 19210 Sin nro. factura no aplica ley», y el voucher PDF «Sin nro. factura
no apli» también cuando la devolución sí se aplicó.

Casos: aplicada, no aplicada (la venta real de Minas del reclamo), cancelada con TaxRefund 1 y
monto 0 (169 en producción) y el cierre del Query que completaba el 0 final con un 1 intermedio.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_oca_core.models.oca_utils import oca_completar_desde_intermedias

# Voucher que devolvió OCA para la venta 02038-001-0003 (Minas, 28-10-2026), recortado.
VOUCHER_SIN_LEY = (
    '<voucher>'
    '<linea><itemLinea>IMPORTE                $   4205.00</itemLinea></linea>'
    '<linea><itemLinea>AUTORI.:631545   FACTURA:        1</itemLinea></linea>'
    '<linea><itemLinea>  Sin Nro Factura No Aplica Ley</itemLinea></linea>'
    '<linea><itemLinea>     ** Original Comercio **</itemLinea></linea>'
    '<linea><itemLinea>  Sin Nro Factura No Aplica Ley</itemLinea></linea>'
    '<linea><itemLinea>       ** Copia Cliente **</itemLinea></linea>'
    '</voucher>'
)


@tagged('post_install', '-at_install')
class TestLeyRespuesta(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tx = cls.env['payment.transaction'].sudo()

    def _tx(self, tid, **respuesta):
        base = {
            'ResponseCode': '0', 'PosID': '30747642', 'TransactionId': tid,
            'TotalAmount': '420500', 'Currency': '858', 'Issuer': '54', 'Acquirer': 5,
            'Ticket': '291', 'AuthorizationCode': '631545', 'TaxableAmount': '344671',
        }
        base.update(respuesta)
        pedido = {'PosID': '30747642', 'Amount': '420500', 'Currency': '858',
                  'TaxRefund': '1', 'InvoiceNumber': '0010003', 'TaxableAmount': '344671'}
        return self.Tx.create_oca_transaction_with_complete_data(
            base, transaction_id=tid, pos_data=pedido,
        )

    def _voucher_pdf(self, tx):
        html = self.env['ir.qweb']._render('odoo_pos_oca.oca_card_voucher_snippet', {
            'tx': tx, 'copy_label': 'COPIA CLIENTE',
            # Lo pasa el informe PDF (ir.actions.report._get_rendering_context).
            'context_timestamp': lambda t: fields.Datetime.context_timestamp(tx, t),
        })
        return ' '.join(str(html).split())

    # Aplicada -------------------------------------------------------------

    def test_aplicada(self):
        tx = self._tx('TX-LEY-APLICADA', TaxRefund='1', TaxAmount='6893', InvoiceNumber='0010003')
        self.assertTrue(tx.get_oca_tax_refund_applied())
        self.assertEqual(tx.tax_refund_code, '1')
        self.assertAlmostEqual(tx.tax_refund_amount, 68.93)
        self.assertEqual(tx.get_oca_tax_refund_law_label(), 'IVA-Ley 19210')
        self.assertEqual(tx.get_oca_tax_refund_reason(), '')
        self.assertEqual(tx.get_oca_invoice_number_sent(), '0010003')
        pdf = self._voucher_pdf(tx)
        self.assertIn('Dev. IVA-Ley 19210', pdf)
        self.assertIn('Aplica dev. IVA-Ley 19210', pdf)
        self.assertNotIn('no apli', pdf.lower())

    def test_aplicada_con_otra_ley(self):
        tx = self._tx('TX-LEY-17934', TaxRefund='4', TaxAmount='1500')
        self.assertTrue(tx.get_oca_tax_refund_applied())
        self.assertIn('Dev. IVA-Ley 17934', self._voucher_pdf(tx))

    # No aplicada ------------------------------------------------------------

    def test_no_aplicada_venta_de_minas(self):
        """La respuesta real del reclamo: ley 0, monto 0, factura 1."""
        tx = self._tx('TX-LEY-MINAS', TaxRefund='0', TaxAmount='0', InvoiceNumber='1',
                      VoucherPrintInfoXML=VOUCHER_SIN_LEY)
        self.assertFalse(tx.get_oca_tax_refund_applied())
        self.assertFalse(tx.tax_refund_code)
        self.assertFalse(tx.tax_refund_amount)
        self.assertEqual(tx.get_oca_tax_refund_reason(), 'Sin Nro Factura No Aplica Ley')
        self.assertEqual(tx.get_oca_invoice_number_sent(), '1')
        pdf = self._voucher_pdf(tx)
        self.assertNotIn('Dev. IVA', pdf)
        self.assertNotIn('Aplica dev.', pdf)
        self.assertIn('Sin Nro Factura No Aplica Ley', pdf)

    def test_no_aplicada_sin_motivo_de_oca(self):
        """Tarjeta de crédito: OCA no aplica ley ni da motivo; no se imprime nada de la ley."""
        tx = self._tx('TX-LEY-CREDITO', TaxRefund='0', TaxAmount='0')
        self.assertFalse(tx.get_oca_tax_refund_applied())
        self.assertEqual(tx.get_oca_tax_refund_reason(), '')
        pdf = self._voucher_pdf(tx)
        self.assertNotIn('Dev. IVA', pdf)
        self.assertNotIn('no apli', pdf.lower())

    def test_cancelada_con_ley_sin_monto_no_es_aplicada(self):
        """169 ventas canceladas de producción: TaxRefund 1 y TaxAmount 0."""
        tx = self._tx('TX-LEY-CANCELADA', TaxRefund='1', TaxAmount='0')
        self.assertEqual(tx.tax_refund_code, '1')
        self.assertFalse(tx.get_oca_tax_refund_applied())
        self.assertNotIn('Dev. IVA', self._voucher_pdf(tx))

    # Cierre del Query -----------------------------------------------------

    def test_cero_final_no_se_pisa_con_un_uno_intermedio(self):
        intermedias = {'TaxRefund': '1', 'Quota': '6'}
        final = {'ResponseCode': '0', 'TaxRefund': '0', 'TaxAmount': '0', 'Quota': '0'}
        oca_completar_desde_intermedias(final, intermedias)
        self.assertEqual(final['TaxRefund'], '0')
        self.assertEqual(final['Quota'], '6', 'Las cuotas siguen completándose como antes')

    def test_dato_que_falta_en_la_final_se_completa(self):
        final = {'ResponseCode': '0'}
        oca_completar_desde_intermedias(final, {'TaxRefund': '1', 'TaxAmount': '6893'})
        self.assertEqual(final['TaxRefund'], '1')
        self.assertEqual(final['TaxAmount'], '6893')

    # Ticket del PDV -------------------------------------------------------

    def test_datos_del_ticket(self):
        orden = self.env['pos.order'].search([('session_id', '!=', False)], order='id desc', limit=1)
        if not orden:
            self.skipTest('Sin órdenes del PDV en la base')
        self.env['payment.transaction'].sudo().search([('pos_order_id', '=', orden.id)]).write(
            {'pos_order_id': False})
        aplicada = self._tx('TX-LEY-TICKET-1', TaxRefund='1', TaxAmount='6893', InvoiceNumber='0010003')
        no_aplicada = self._tx('TX-LEY-TICKET-2', TaxRefund='0', TaxAmount='0', InvoiceNumber='1',
                               VoucherPrintInfoXML=VOUCHER_SIN_LEY)
        (aplicada | no_aplicada).write({'pos_order_id': orden.id})
        vouchers = self.env['pos.order'].get_oca_voucher_dict_for_pos_receipt(order_id=orden.id)
        por_factura = {v['invoice_number']: v for v in vouchers}
        self.assertTrue(por_factura['0010003']['tax_refund_applied'])
        self.assertEqual(por_factura['0010003']['tax_law_label'], 'IVA-Ley 19210')
        self.assertEqual(por_factura['0010003']['tax_refund_reason'], '')
        self.assertFalse(por_factura['1']['tax_refund_applied'])
        self.assertEqual(por_factura['1']['tax_refund_reason'], 'Sin Nro Factura No Aplica Ley')
