# -*- coding: utf-8 -*-
"""El recibo reintenta el CFE que quedó pendiente y, si no sale, avisa.

Con la emisión después del posteo (LocalizacionUy), un fallo de UCFE ya no corta
la venta: la factura queda registrada con el CFE pendiente. El recibo es lo
primero que pide el PDV después de guardar la venta (Forum, 02-11-2026).
"""
import unittest
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCfePendienteRecibo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Move = cls.env['account.move']
        if 'uy_cfe_pendiente' not in Move._fields:
            raise unittest.SkipTest('Sin la emisión después del posteo de LocalizacionUy')
        cls.env.company.sudo().fe_activa = True
        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.env.company.id)], limit=1)
        if not cls.journal:
            raise unittest.SkipTest('No hay diario de ventas en la compañía')
        cls.journal.sudo().diario_cfe = True
        cls.partner = cls.env['res.partner'].create({'name': 'Consumidor recibo CFE'})

    def _factura_pendiente(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'journal_id': self.journal.id,
            'partner_id': self.partner.id,
            'invoice_date': fields.Date.context_today(self.env.user),
            'invoice_line_ids': [(0, 0, {'name': 'Prenda', 'quantity': 1, 'price_unit': 100.0,
                                         'tax_ids': [(5, 0, 0)]})],
        })
        if invoice.journal_id.l10n_latam_use_documents and not invoice.l10n_latam_document_type_id:
            disponibles = invoice.l10n_latam_available_document_type_ids
            if not disponibles:
                self.skipTest('El diario no tiene tipos de documento latam')
            invoice.l10n_latam_document_type_id = disponibles[0]
        # Registrada sin emitir: como queda cuando UCFE no contestó.
        invoice.with_context(dont_send_to_dgi=True).action_post()
        self.assertTrue(invoice.uy_cfe_pendiente)
        return invoice

    def _datos(self, invoice, **kw):
        return self.env['pos.order'].get_cfe_data_from_invoice([], invoice.id, **kw)

    def test_01_si_no_sale_avisa_con_el_motivo(self):
        invoice = self._factura_pendiente()

        def _caido(move_self):
            raise ValidationError('503, UCFE no responde')

        with patch.object(type(self.env['account.move']), 'action_uy_emitir_cfe', _caido):
            datos = self._datos(invoice, reintentar=True)
        self.assertTrue(datos['cfe_pendiente'])
        self.assertIn('UCFE no responde', datos['cfe_error'])

    def test_02_si_sale_el_recibo_ya_no_esta_pendiente(self):
        invoice = self._factura_pendiente()
        llamadas = []

        def _emite(move_self):
            llamadas.append(move_self.ids)
            move_self.cfe_emitido = True
            return True

        with patch.object(type(self.env['account.move']), 'action_uy_emitir_cfe', _emite):
            datos = self._datos(invoice, reintentar=True)
        self.assertEqual(llamadas, [invoice.ids])
        self.assertFalse(datos.get('cfe_pendiente'))
        self.assertFalse(datos.get('cfe_error'))
        self.assertFalse(invoice.uy_cfe_pendiente)

    def test_03_las_otras_vias_no_reintentan(self):
        """Impresión, QZ y reimpresión corren en paralelo con el recibo: no emiten."""
        invoice = self._factura_pendiente()
        llamadas = []
        with patch.object(type(self.env['account.move']), 'action_uy_emitir_cfe',
                          lambda s: llamadas.append(s.ids)):
            datos = self._datos(invoice)
        self.assertFalse(llamadas)
        self.assertTrue(datos['cfe_pendiente'])
