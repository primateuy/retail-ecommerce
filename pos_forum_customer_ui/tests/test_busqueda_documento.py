# -*- coding: utf-8 -*-
"""Búsqueda de clientes por documento desde el PDV.

Con ~660.000 clientes, la búsqueda de Odoo (12 campos, en cualquier parte del texto) tardaba
3,3 s en producción. El PDV ahora busca un número sólo por el comienzo del documento, y eso
necesita un índice con `text_pattern_ops`: con la configuración regional de la base, el índice
común de `vat` no sirve para `LIKE '4184%'`.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBusquedaDocumento(TransactionCase):

    def test_indice_prefijo_existe(self):
        self.env.cr.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'res_partner_vat_prefijo_index'")
        fila = self.env.cr.fetchone()
        self.assertTrue(fila, "Falta el índice res_partner_vat_prefijo_index")
        self.assertIn('text_pattern_ops', fila[0])

    def test_prefijo_usa_el_indice(self):
        self.env.cr.execute("SET LOCAL enable_seqscan = off")
        self.env.cr.execute("EXPLAIN SELECT id FROM res_partner WHERE vat LIKE '4184%%'")
        plan = ' '.join(r[0] for r in self.env.cr.fetchall())
        self.assertIn('res_partner_vat_prefijo_index', plan)

    def test_encuentra_documento_con_ceros(self):
        """La cajera escribe la CI sin el cero de adelante: el dominio del PDV la encuentra."""
        socio = self.env['res.partner'].create({'name': 'Con ceros'})
        # Por SQL: es un documento viejo, que hoy no pasaría la validación de la CI.
        self.env.cr.execute("UPDATE res_partner SET vat = '00030172641' WHERE id = %s", [socio.id])
        socio.invalidate_recordset(['vat'])
        base = '30172641'
        variantes = [['vat', '=like', c + base + '%'] for c in ('', '0', '00', '000')]
        dominio = ['|'] * 3 + variantes
        self.assertIn(socio, self.env['res.partner'].search(dominio))
