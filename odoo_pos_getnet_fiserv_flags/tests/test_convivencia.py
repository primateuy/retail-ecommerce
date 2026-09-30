# -*- coding: utf-8 -*-
"""
Getnet y Fiserv instalados en la misma base v19: los guards, los flags y el
form del pago no se pisan. Todo el transporte está mockeado.
"""

import uuid
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_fiserv_core.models import fiserv_utils


@tagged('post_install', '-at_install')
class TestConvivenciaGetnetFiserv(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente convivencia'})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Banco convivencia', 'code': 'CONV', 'type': 'bank'})
        cuenta = cls.env['account.account'].create({
            'name': 'Pendiente convivencia', 'code': 'CONVPEND',
            'account_type': 'asset_current', 'reconcile': True})

        # Fiserv: el proveedor crea sus dos líneas al recibir diario.
        cls.fiserv = cls.env['payment.provider'].create({
            'name': 'Fiserv conv', 'code': 'fiserv', 'state': 'test',
            'fiserv_url_webservice': 'https://itd.example.invalid',
            'fiserv_system_id': 'SYSFAKE0002',
        })
        cls.fiserv_terminal = cls.env['fiserv.pos.terminal'].create({
            'name': 'Caja F', 'pos_id': 'P0009', 'payment_provider_id': cls.fiserv.id})
        cls.fiserv.journal_id = cls.journal
        cls.line_fiserv = cls.env['account.payment.method.line'].search([
            ('payment_provider_id', '=', cls.fiserv.id), ('payment_type', '=', 'inbound')])

        # Getnet: mismo diario, su propia línea.
        cls.getnet = cls.env['payment.provider'].create({
            'name': 'Getnet conv', 'code': 'getnet', 'state': 'test',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE', 'getnet_emp_hash': 'HASHFALSO',
        })
        cls.getnet_terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Caja G', 'term_cod': 'T00009', 'payment_provider_id': cls.getnet.id})
        # El mecanismo estándar: al recibir diario, el core le crea su línea.
        cls.getnet.journal_id = cls.journal
        cls.line_getnet = cls.env['account.payment.method.line'].search([
            ('payment_provider_id', '=', cls.getnet.id), ('payment_type', '=', 'inbound')])
        (cls.line_fiserv | cls.line_getnet).write({'payment_account_id': cuenta.id})

    def _pago(self, line, **vals):
        return self.env['account.payment'].create(dict({
            'payment_type': 'inbound', 'partner_type': 'customer',
            'partner_id': self.partner.id, 'amount': 50.0,
            'journal_id': self.journal.id, 'payment_method_line_id': line.id,
        }, **vals))

    def _tx(self, provider, method_xmlid, **vals):
        tx = self.env['payment.transaction'].create(dict({
            'provider_id': provider.id,
            'payment_method_id': self.env.ref(method_xmlid).id,
            'reference': 'CONV-%s' % uuid.uuid4().hex[:10],
            'amount': 50.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.partner.id,
        }, **vals))
        tx._set_done()
        return tx

    def _contador(self):
        return self.env['res.users'].create({
            'name': 'Contador conv', 'login': 'conv.%s' % uuid.uuid4().hex[:8],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('account.group_account_user').id])],
        })

    # ------------------------------------------------------------------
    def test_el_puente_se_instala_solo(self):
        modulo = self.env['ir.module.module'].search([('name', '=', 'odoo_pos_getnet_fiserv_flags')])
        self.assertEqual(modulo.state, 'installed')
        self.assertTrue(modulo.auto_install)

    def test_los_dos_proveedores_de_la_instalacion_nacen_apagados(self):
        for xmlid in ('odoo_pos_fiserv_core.payment_provider_fiserv',
                      'odoo_pos_getnet_core.payment_provider_getnet'):
            self.assertEqual(self.env.ref(xmlid).state, 'disabled', xmlid)

    def test_pago_getnet_con_check_fiserv_pegado_se_confirma(self):
        """
        El caso que originó el puente en 17.0: el check Fiserv pegado en un
        pago Getnet ocultaba Confirmar para siempre, aun con el cobro Getnet
        aprobado en el pinpad.
        """
        pago = self._pago(self.line_getnet, getnet_charge_on_pos=True,
                          getnet_terminal_id=self.getnet_terminal.id,
                          fiserv_charge_on_pos=True)
        pago.getnet_transaction_id = self._tx(
            self.getnet, 'odoo_pos_getnet_core.payment_method_getnet',
            getnet_account_payment_id=pago.id)
        self.assertFalse(pago.pos_integrated_post_blocked)
        self.assertFalse(pago.getnet_post_blocked)
        pago.action_post()
        self.assertIn(pago.state, ('in_process', 'paid'))

    def test_pago_fiserv_con_check_getnet_pegado_se_confirma(self):
        pago = self._pago(self.line_fiserv, fiserv_charge_on_pos=True,
                          fiserv_terminal_id=self.fiserv_terminal.id,
                          getnet_charge_on_pos=True)
        pago.payment_transaction_id = self._tx(
            self.fiserv, 'odoo_pos_fiserv_core.payment_method_fiserv', account_payment_id=pago.id)
        self.assertFalse(pago.getnet_post_blocked)
        self.assertFalse(pago.pos_integrated_post_blocked)
        pago.action_post()
        self.assertIn(pago.state, ('in_process', 'paid'))

    def test_cada_pago_sigue_bloqueado_por_su_propio_adquirente(self):
        """El puente neutraliza al AJENO, nunca al propio."""
        fiserv = self._pago(self.line_fiserv, getnet_charge_on_pos=True)
        getnet = self._pago(self.line_getnet, fiserv_charge_on_pos=True)
        self.assertTrue(fiserv.pos_integrated_post_blocked)
        self.assertTrue(getnet.getnet_post_blocked)
        for pago in (fiserv, getnet):
            with self.assertRaises(UserError):
                pago.action_post()

    def test_un_cobro_getnet_en_curso_bloquea_igual(self):
        """Plata en movimiento en el pinpad: bloquea aunque la línea sea la otra."""
        pago = self._pago(self.line_fiserv)
        pago.getnet_async_terminal_pending = True
        self.assertTrue(pago.getnet_post_blocked)

    def test_cobrar_por_fiserv_limpia_el_check_getnet(self):
        pago = self._pago(self.line_fiserv, fiserv_charge_on_pos=True,
                          fiserv_terminal_id=self.fiserv_terminal.id,
                          getnet_charge_on_pos=True, getnet_terminal_id=self.getnet_terminal.id)
        Provider = type(self.env['payment.provider'])
        with patch.object(Provider, '_fiserv_start_purchase',
                          lambda p, d: {'ResponseCode': '0', 'TransactionId': '1'}), \
                patch.object(type(pago), '_fiserv_start_worker_thread', lambda *a: None), \
                patch.object(fiserv_utils, 'fiserv_safe_commit', lambda env: None):
            pago.action_fiserv_create_transaction()
        self.assertFalse(pago.getnet_charge_on_pos)
        self.assertFalse(pago.getnet_terminal_id)
        self.assertEqual(pago.payment_transaction_id.state, 'pending')

    def test_cobrar_por_getnet_limpia_el_check_fiserv(self):
        pago = self._pago(self.line_getnet, getnet_charge_on_pos=True,
                          getnet_terminal_id=self.getnet_terminal.id,
                          fiserv_charge_on_pos=True, fiserv_terminal_id=self.fiserv_terminal.id)
        Provider = type(self.env['payment.provider'])
        rechazo = ({'Resp_CodigoRespuesta': '2', 'Resp_MensajeError': 'CAMPO'}, '<r/>', '<r/>')
        try:
            with patch.object(Provider, '_getnet_soap_transaccion', lambda p, m, params: rechazo):
                pago.action_getnet_create_transaction()
        except UserError:
            pass
        self.assertFalse(pago.fiserv_charge_on_pos)
        self.assertFalse(pago.fiserv_terminal_id)

    def test_el_onchange_limpia_el_check_del_otro(self):
        pago = self._pago(self.line_fiserv, getnet_charge_on_pos=True)
        pago._onchange_getnet_fiserv_limpia_checks()
        self.assertFalse(pago.getnet_charge_on_pos)
        pago.payment_method_line_id = self.line_getnet
        pago.fiserv_charge_on_pos = True
        pago._onchange_getnet_fiserv_limpia_checks()
        self.assertFalse(pago.fiserv_charge_on_pos)

    def test_el_form_suma_los_terminos_de_los_dos(self):
        """Aditivo en los dos backends: ningún término se come al otro."""
        arch = etree.fromstring(self.env['account.payment'].with_user(self._contador())
                                .get_view(view_type='form')['arch'])

        def invisible(nombre):
            return arch.xpath("//header/button[@name='%s']" % nombre)[0].get('invisible')

        confirmar = invisible('action_post')
        self.assertIn('getnet_post_blocked', confirmar)
        self.assertIn('pos_integrated_post_blocked', confirmar)
        borrador = invisible('action_draft')
        self.assertIn('getnet_draft_blocked', borrador)
        self.assertIn('pos_integrated_draft_blocked', borrador)
        self.assertIn('cfe_emitido', borrador)
        self.assertIn('pos_integrated_cancel_blocked', invisible('action_cancel'))
        self.assertIn('getnet_cancel_blocked', invisible('action_cancel'))
        self.assertTrue(arch.xpath("//button[@name='action_fiserv_create_transaction']"))
        self.assertTrue(arch.xpath("//button[@name='action_getnet_create_transaction']"))

    def test_el_contador_abre_pagos_de_los_dos(self):
        contador = self._contador()
        for line, campo in ((self.line_fiserv, 'fiserv_is_fiserv_payment_line'),
                            (self.line_getnet, 'getnet_is_getnet_payment_line')):
            pago = self._pago(line).with_user(contador)
            pago.invalidate_recordset()
            datos = pago.read([campo, 'pos_integrated_post_blocked', 'getnet_post_blocked'])[0]
            self.assertTrue(datos[campo])

    def test_pagar_desde_la_factura_carga_las_facturas_para_los_dos(self):
        ventas = self.env['account.journal'].create({
            'name': 'Ventas conv', 'code': 'CVTA', 'type': 'sale',
            'l10n_latam_use_documents': False})
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id, 'journal_id': ventas.id,
            'invoice_line_ids': [(0, 0, {'name': 'x', 'quantity': 1, 'price_unit': 50.0,
                                         'tax_ids': [(5, 0, 0)]})],
        })
        invoice.action_post()
        ctx = invoice.action_fiserv_register_payment()['context']
        self.assertEqual(ctx['default_fiserv_source_invoice_ids'], [(6, 0, invoice.ids)])
        self.assertEqual(ctx['default_getnet_source_invoice_ids'], [(6, 0, invoice.ids)])

    def test_la_transaccion_original_es_de_su_adquirente(self):
        """Una devolución Fiserv no puede elegir un cobro Getnet (ni al revés)."""
        tx_getnet = self._tx(self.getnet, 'odoo_pos_getnet_core.payment_method_getnet',
                             ticket_number='1')
        dominio = self.env['account.payment']._fields['fiserv_original_transaction_id'].domain
        dominio = dominio.replace("'=', company_id)", "'=', %d)" % self.env.company.id)
        self.assertNotIn(tx_getnet, self.env['payment.transaction'].search(eval(dominio)))
