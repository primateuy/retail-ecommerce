# -*- coding: utf-8 -*-
"""
Tests del flujo contable Getnet: payload de factura (regresión del anexo
del manual sobre una factura real), guards de post/cancel/draft,
devoluciones outbound y worker sincrónico con SOAP mockeado.
"""

import uuid
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_getnet_backend.models import (
    account_payment as ap_mod,
)
from odoo.addons.odoo_pos_getnet_core.models import getnet_utils
from odoo.addons.odoo_pos_getnet_core.models import (
    payment_transaction as pt_mod,
)
from odoo.addons.odoo_pos_getnet_core.tests.common import _RelojDeLaboratorio

# Nombres del WSDL real (enum de strings, Resp_TransaccionFinalizada).
APROBADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE',
    'Resp_TransaccionFinalizada': 'true',
    'Aprobada': 'true',
    'TransaccionId': '555',
    'Ticket': '901',
    'Lote': '7',
    'NroAutorizacion': 'B1234',
    'MsgRespuesta': 'APROBADA',
}
DENEGADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_ERROR',
    'Resp_TransaccionFinalizada': 'true',
    'Aprobada': 'false',
    'CodRespAdq': '51',
    'Ticket': '0',
    'Lote': '0',
    'MsgRespuesta': 'DENEGADA',
}


@tagged('post_install', '-at_install')
class TestGetnetBackend(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Getnet Backend Test',
            'code': 'getnet',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE',
            'getnet_emp_hash': 'HASH',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Caja Backend',
            'term_cod': 'T00002',
            'payment_provider_id': cls.provider.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Backend'})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Getnet Test',
            'code': 'GETN',
            'type': 'bank',
        })
        cls.apm = cls.env['account.payment.method'].sudo().create({
            'name': 'Getnet inbound',
            'code': 'getnet_test_in',
            'payment_type': 'inbound',
        })
        cls.apm_line = cls.env['account.payment.method.line'].create({
            'journal_id': cls.journal.id,
            'payment_method_id': cls.apm.id,
            'payment_provider_id': cls.provider.id,
        })
        cls.tax22 = cls.env['account.tax'].create({
            'name': 'IVA 22 test', 'amount': 22.0, 'type_tax_use': 'sale'})
        cls.tax10 = cls.env['account.tax'].create({
            'name': 'IVA 10 test', 'amount': 10.0, 'type_tax_use': 'sale'})
        cls.env['payment.transaction'].search([
            ('provider_id.code', '=', 'getnet'),
            ('state', 'in', ('draft', 'pending')),
            ('getnet_token', '!=', False),
        ]).write({'getnet_token': False})

    def _create_payment(self, **vals):
        base = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 100.0,
            'journal_id': self.journal.id,
            'payment_method_line_id': self.apm_line.id,
            'getnet_charge_on_pos': True,
            'getnet_terminal_id': self.terminal.id,
        }
        base.update(vals)
        return self.env['account.payment'].create(base)

    def _assert_confirmado(self, payment):
        """
        Confirmar un pago en 19.0 NO lo deja en 'posted' (ese valor ya no
        existe en account.payment): queda en 'in_process', o en 'paid' si
        la cuenta pendiente del método es de caja. Se asserta contra la
        misma constante que usa el módulo para decidir si concilia.
        """
        payment.invalidate_recordset(['state'])
        self.assertIn(payment.state, ap_mod.GETNET_PAYMENT_CONFIRMADO)

    def _create_invoice_anexo(self):
        """Factura del anexo: 100 al 22%, 100 al 10%, 100 exento."""
        journal_venta = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('code', '=', 'GVTA')], limit=1)
        if not journal_venta:
            # Sin documentos latam: el payload no depende de la secuencia
            # del CFE en este test, solo de montos y numero_cfe()
            journal_venta = self.env['account.journal'].create({
                'name': 'Ventas Getnet Test',
                'code': 'GVTA',
                'type': 'sale',
                'l10n_latam_use_documents': False,
            })
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal_venta.id,
            'partner_id': self.partner.id,
            'invoice_line_ids': [
                (0, 0, {'name': 'básica', 'quantity': 1, 'price_unit': 100.0,
                        'tax_ids': [(6, 0, self.tax22.ids)]}),
                (0, 0, {'name': 'mínima', 'quantity': 1, 'price_unit': 100.0,
                        'tax_ids': [(6, 0, self.tax10.ids)]}),
                (0, 0, {'name': 'exento', 'quantity': 1, 'price_unit': 100.0,
                        'tax_ids': [(5, 0, 0)]}),
            ],
        })
        invoice.action_post()
        self._sellar_cfe(invoice)
        return invoice

    # Respuesta de firma de Uruware, recortada a lo que numero_cfe() lee.
    # Los prefijos de namespace van sin declarar a propósito: es la forma
    # exacta en que el módulo la parsea (xmltodict sobre expat, sin
    # procesamiento de namespaces).
    CFE_FIRMADO = (
        '<RespBody><Resp>'
        '<a:NumeroCfe>%(numero)s</a:NumeroCfe>'
        '<a:Serie>A</a:Serie>'
        '</Resp></RespBody>')

    def _sellar_cfe(self, invoice, numero=None, cfe_type='101'):
        """
        Deja la factura como si Uruware ya la hubiera firmado.

        Hace falta porque numero_cfe() NO es el de l10n_uy_einvoice_base en
        una instalación real: l10n_uy_einvoice_uruware lo sobrescribe y exige
        el CFE firmado. Probar contra el de base daría verde sobre un camino
        que en el cliente no se ejecuta nunca.
        """
        if numero is None:
            numero = 1000 + invoice.id
        invoice.sudo().write({
            'cfe': self.CFE_FIRMADO % {'numero': numero},
            'cfe_type': cfe_type,
        })
        return numero

    def _create_done_tx(self, payment):
        method = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': method.id,
            'reference': 'GETNET-BK-%s' % uuid.uuid4().hex[:10],
            'amount': payment.amount,
            'currency_id': payment.currency_id.id,
            'partner_id': self.partner.id,
            'getnet_ticket': '901',
            'getnet_account_payment_id': payment.id,
        })
        tx._set_done()
        payment.getnet_transaction_id = tx
        return tx

    # ------------------------------------------------------------------
    # Payload de factura
    # ------------------------------------------------------------------
    def test_factura_vals_anexo_regresion(self):
        """
        Regresión permanente del anexo del manual sobre una factura REAL:
        33200 / 20000 / 3200 y FacturaNro desde numero_cfe().
        """
        invoice = self._create_invoice_anexo()
        payment = self._create_payment(
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        vals = payment._getnet_factura_vals_from_move(invoice)
        self.assertEqual(vals['FacturaMonto'], 33200)
        self.assertEqual(vals['FacturaMontoGravado'], 20000)
        self.assertEqual(vals['FacturaMontoIVA'], 3200)
        # FacturaNro es numérico en el contrato (xs:double), no texto
        self.assertEqual(vals['FacturaNro'], int(invoice.numero_cfe()))
        self.assertTrue(vals['FacturaNro'])

    def test_payload_completo_inbound(self):
        invoice = self._create_invoice_anexo()
        payment = self._create_payment(
            amount=332.0,
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        vals = payment._getnet_prepare_transaccion_vals(
            self.provider, self.terminal)
        self.assertEqual(vals['Operacion'], 'VTA')
        self.assertEqual(vals['Monto'], 33200)
        self.assertEqual(vals['EmpCod'], 'NEWAGE')
        self.assertEqual(vals['TermCod'], 'T00002')
        self.assertIn(vals['MonedaISO'], ('0858', '0840'))
        self.assertEqual(vals['FacturaMontoGravado'], 20000)
        # DecretoLeyId sin setear: lo solicita el POS (manual)
        self.assertNotIn('DecretoLeyId', vals)

    def test_factura_sin_cfe_firmado_da_error_que_nombra_la_factura(self):
        """
        Con uruware instalado, numero_cfe() levanta ValidationError cuando la
        factura no está firmada. El error que ve el contador tiene que decir
        QUÉ factura y que lo que falló fue el cobro Getnet.
        """
        invoice = self._create_invoice_anexo()
        invoice.sudo().write({'cfe': False})
        payment = self._create_payment(
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        with self.assertRaises(UserError) as capturado:
            payment._getnet_factura_vals_from_move(invoice)
        self.assertIn(invoice.name, str(capturado.exception))

    def test_consumidor_final_viaja_segun_el_cfe_de_la_factura(self):
        """e-Ticket => consumidor final; e-Factura => no."""
        ticket = self._create_invoice_anexo()
        pago_ticket = self._create_payment(
            getnet_source_invoice_ids=[(6, 0, ticket.ids)])
        self.assertTrue(
            pago_ticket._getnet_factura_vals_from_move(ticket)
            ['FacturaConsumidorFinal'])

        efactura = self._create_invoice_anexo()
        self._sellar_cfe(efactura, cfe_type='111')
        pago_efactura = self._create_payment(
            getnet_source_invoice_ids=[(6, 0, efactura.ids)])
        self.assertFalse(
            pago_efactura._getnet_factura_vals_from_move(efactura)
            ['FacturaConsumidorFinal'])

    def test_consumidor_final_por_tipo_cfe(self):
        from odoo.addons.odoo_pos_getnet_backend.models.account_payment \
            import GETNET_CFE_CONSUMIDOR_FINAL
        self.assertIn('101', GETNET_CFE_CONSUMIDOR_FINAL)   # e-Ticket
        self.assertIn('102', GETNET_CFE_CONSUMIDOR_FINAL)   # NC e-Ticket
        self.assertNotIn('111', GETNET_CFE_CONSUMIDOR_FINAL)  # e-Factura
        self.assertNotIn('112', GETNET_CFE_CONSUMIDOR_FINAL)

    # FacturaNro es obligatorio para el concentrador (rc=2 si se omite);
    # los montos y ConsumidorFinal sí son opcionales de verdad.
    FACTURA_KEYS_OPCIONALES = ('FacturaMonto', 'FacturaMontoGravado',
                               'FacturaMontoIVA', 'FacturaConsumidorFinal')

    def test_multiples_facturas_postea_sin_datos_de_factura(self):
        """
        Criterio de New Age Data: con varias facturas no hay FacturaNro
        único, así que se OMITEN todos los Factura* y se postea igual (ya
        no bloquea).
        """
        inv1 = self._create_invoice_anexo()
        inv2 = self._create_invoice_anexo()
        payment = self._create_payment(
            getnet_source_invoice_ids=[(6, 0, (inv1 + inv2).ids)])
        payment._getnet_validate_before_charge(self.provider)
        vals = payment._getnet_prepare_transaccion_vals(
            self.provider, self.terminal)
        self.assertEqual(vals['FacturaNro'], 0)
        for clave in self.FACTURA_KEYS_OPCIONALES:
            self.assertNotIn(clave, vals)
        self.assertEqual(vals['Operacion'], 'VTA')
        self.assertTrue(vals['Monto'])

    def test_pago_sin_factura_postea_sin_datos_de_factura(self):
        """Cobro suelto (sin factura origen): mismo criterio."""
        payment = self._create_payment()
        payment._getnet_validate_before_charge(self.provider)
        vals = payment._getnet_prepare_transaccion_vals(
            self.provider, self.terminal)
        self.assertEqual(vals['FacturaNro'], 0)
        for clave in self.FACTURA_KEYS_OPCIONALES:
            self.assertNotIn(clave, vals)

    def test_sin_factura_el_envelope_lleva_factura_nro_cero(self):
        """
        El envelope debe llevar FacturaNro (el concentrador lo exige:
        omitirlo da rc=2 CAMPO REQUERIDO ... FACTURA) y NINGUNO de los
        Factura* opcionales.
        """
        payment = self._create_payment()
        vals = payment._getnet_prepare_transaccion_vals(
            self.provider, self.terminal)
        envelope = getnet_utils.getnet_build_soap_envelope(
            'PostearTransaccion', {'Transaccion': vals}).decode('utf-8')
        self.assertIn('<dc:FacturaNro>0</dc:FacturaNro>', envelope)
        for clave in self.FACTURA_KEYS_OPCIONALES:
            self.assertNotIn(clave, envelope)
        self.assertIn('<dc:Monto>', envelope)

    def test_moneda_no_soportada_rechaza(self):
        eur = self.env.ref('base.EUR')
        payment = self._create_payment(currency_id=eur.id)
        with self.assertRaises(UserError):
            payment._getnet_validate_before_charge(self.provider)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def test_post_bloqueado_sin_tx_aprobada(self):
        payment = self._create_payment()
        with self.assertRaises(UserError):
            payment.action_post()

    def test_post_ok_con_tx_aprobada(self):
        payment = self._create_payment()
        self._create_done_tx(payment)
        payment.action_post()
        self._assert_confirmado(payment)

    def test_cancel_bloqueado_con_tx_aprobada(self):
        payment = self._create_payment()
        self._create_done_tx(payment)
        with self.assertRaises(UserError):
            payment.action_cancel()

    def test_draft_bloqueado_con_tx_aprobada(self):
        payment = self._create_payment()
        self._create_done_tx(payment)
        payment.action_post()
        with self.assertRaises(UserError):
            payment.action_draft()

    def test_reject_bloqueado_con_tx_aprobada(self):
        """Rechazar (botón nuevo de 19.0) no revierte un cobro aprobado."""
        payment = self._create_payment()
        self._create_done_tx(payment)
        payment.action_post()
        with self.assertRaises(UserError):
            payment.action_reject()

    def test_estados_confirmados_existen_en_el_core(self):
        """
        La conciliación con las facturas origen depende de comparar el
        estado del pago contra GETNET_PAYMENT_CONFIRMADO. Si una versión
        renombra esos valores, la comparación devuelve False para todo y
        la conciliación deja de correr SIN fallar. Esto lo caza.
        """
        valores = dict(
            self.env['account.payment']._fields['state'].selection)
        for estado in ap_mod.GETNET_PAYMENT_CONFIRMADO:
            self.assertIn(estado, valores)
        self.assertNotIn('posted', valores)

    def test_post_bloqueado_con_worker_pendiente(self):
        payment = self._create_payment()
        self._create_done_tx(payment)
        payment.getnet_async_terminal_pending = True
        with self.assertRaises(UserError):
            payment.action_post()

    # ------------------------------------------------------------------
    # Flags de visibilidad propios (standalone, sin Fiserv en la BD)
    # ------------------------------------------------------------------
    def test_flags_vista_sin_tx(self):
        """Sin transacción aprobada: Confirmar oculto, Cancelar/Borrador no."""
        payment = self._create_payment()
        self.assertTrue(payment.getnet_post_blocked)
        self.assertFalse(payment.getnet_cancel_blocked)
        self.assertFalse(payment.getnet_draft_blocked)

    def test_flags_vista_con_tx_aprobada(self):
        """Cobro aprobado: se habilita Confirmar y se bloquean los otros."""
        payment = self._create_payment()
        self._create_done_tx(payment)
        payment.invalidate_recordset()
        self.assertFalse(payment.getnet_post_blocked)
        self.assertTrue(payment.getnet_cancel_blocked)
        self.assertTrue(payment.getnet_draft_blocked)

    def test_flags_vista_con_worker_pendiente(self):
        """Worker en curso: los tres botones ocultos."""
        payment = self._create_payment()
        self._create_done_tx(payment)
        payment.getnet_async_terminal_pending = True
        self.assertTrue(payment.getnet_post_blocked)
        self.assertTrue(payment.getnet_cancel_blocked)
        self.assertTrue(payment.getnet_draft_blocked)

    def test_flags_vista_pago_ajeno_a_getnet(self):
        """Pago sin proveedor Getnet: ningún botón se toca."""
        apm = self.env['account.payment.method'].sudo().create({
            'name': 'Manual test flags',
            'code': 'getnet_flags_manual',
            'payment_type': 'inbound',
        })
        journal = self.env['account.journal'].create({
            'name': 'Banco sin Getnet', 'code': 'NGET', 'type': 'bank'})
        line = self.env['account.payment.method.line'].create({
            'journal_id': journal.id, 'payment_method_id': apm.id})
        payment = self._create_payment(
            journal_id=journal.id, payment_method_line_id=line.id,
            getnet_charge_on_pos=False, getnet_terminal_id=False)
        self.assertFalse(payment.getnet_post_blocked)
        self.assertFalse(payment.getnet_cancel_blocked)
        self.assertFalse(payment.getnet_draft_blocked)
        payment.action_post()
        self._assert_confirmado(payment)

    def test_flags_vista_espejan_los_guards(self):
        """El flag de vista no puede permitir lo que el servidor rechaza."""
        payment = self._create_payment()
        self.assertTrue(payment.getnet_post_blocked)
        with self.assertRaises(UserError):
            payment.action_post()

    # ------------------------------------------------------------------
    # Devoluciones
    # ------------------------------------------------------------------
    def test_outbound_requiere_tx_original(self):
        payment = self._create_payment(
            payment_type='outbound', partner_type='supplier')
        with self.assertRaises(UserError):
            payment._getnet_validate_before_charge(self.provider)

    def test_outbound_payload_dev_con_ticket(self):
        inbound = self._create_payment(amount=250.0)
        tx_orig = self._create_done_tx(inbound)
        outbound = self._create_payment(
            payment_type='outbound', partner_type='supplier',
            amount=250.0, getnet_original_transaction_id=tx_orig.id)
        outbound._getnet_validate_before_charge(self.provider)
        vals = outbound._getnet_prepare_transaccion_vals(
            self.provider, self.terminal)
        self.assertEqual(vals['Operacion'], 'DEV')
        # TicketOriginal es xs:int en el contrato (el Ticket se persiste
        # como texto porque llega en un xs:double)
        self.assertEqual(vals['TicketOriginal'], 901)
        self.assertEqual(vals['Monto'], 25000)
        self.assertNotIn('FacturaNro', vals)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def test_worker_inner_denegada_no_habilita_confirmar(self):
        """
        Finalizada con error: tx en error, pago sigue en borrador, sin lote
        y con Confirmar todavía bloqueado (no hay cobro que registrar).
        """
        payment = self._create_payment()
        method = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': method.id,
            'reference': 'GETNET-BK-%s' % uuid.uuid4().hex[:10],
            'amount': 100.0,
            'currency_id': payment.currency_id.id,
            'partner_id': self.partner.id,
            'getnet_token': 'TOK-BK-DEN',
            'getnet_terminal_id': self.terminal.id,
            'getnet_account_payment_id': payment.id,
        })
        payment.getnet_transaction_id = tx

        def fake_soap(prov, method_name, params):
            return (dict(DENEGADA), '<req/>', '<resp/>')

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 5])):
            payment._getnet_worker_inner(
                tx, self.terminal, self.provider, 1)
        self.assertEqual(tx.state, 'error')
        self.assertFalse(tx.getnet_lote)
        self.assertFalse(self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id)]))
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'draft')
        self.assertFalse(payment.getnet_tx_is_done)
        self.assertTrue(payment.getnet_post_blocked)
        with self.assertRaises(UserError):
            payment.action_post()

    def test_worker_inner_aprobada_no_autopostea(self):
        """Aprobada: tx done, pago SIGUE en borrador, chatter avisa."""
        payment = self._create_payment()
        method = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': method.id,
            'reference': 'GETNET-BK-%s' % uuid.uuid4().hex[:10],
            'amount': 100.0,
            'currency_id': payment.currency_id.id,
            'partner_id': self.partner.id,
            'getnet_token': 'TOK-BK-1',
            'getnet_terminal_id': self.terminal.id,
            'getnet_account_payment_id': payment.id,
        })
        payment.getnet_transaction_id = tx

        def fake_soap(prov, method_name, params):
            return (dict(APROBADA), '<req/>', '<resp/>')

        mensajes_antes = len(payment.message_ids)
        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 5])):
            payment._getnet_worker_inner(
                tx, self.terminal, self.provider, 1)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.getnet_ticket, '901')
        self.assertEqual(payment.state, 'draft')
        self.assertGreater(len(payment.message_ids), mensajes_antes)
        # Con la tx aprobada, ahora sí se puede confirmar
        payment.action_post()
        self._assert_confirmado(payment)

    # ------------------------------------------------------------------
    # Multi-terminal en el flujo contable
    # ------------------------------------------------------------------
    def _segunda_terminal(self):
        """Habilita el modo multi-terminal con un segundo pinpad."""
        self.provider.getnet_is_multiple = True
        return self.env['getnet.pos.terminal'].create({
            'name': 'Caja Backend 2',
            'term_cod': 'T00004',
            'payment_provider_id': self.provider.id,
        })

    def test_con_una_terminal_no_se_pide_elegir(self):
        """Terminal única: el campo no se muestra y se preselecciona."""
        payment = self._create_payment(getnet_terminal_id=False)
        payment._onchange_getnet_auto_charge_integrated_journal()
        self.assertFalse(payment.getnet_need_terminal_choice)
        self.assertEqual(payment.getnet_terminal_id, self.terminal)

    def test_con_dos_terminales_hay_que_elegir(self):
        """Con más de una: se pide elegir y no se preselecciona ninguna."""
        terminal2 = self._segunda_terminal()
        payment = self._create_payment(getnet_terminal_id=False)
        payment._onchange_getnet_auto_charge_integrated_journal()
        self.assertTrue(payment.getnet_need_terminal_choice)
        self.assertFalse(payment.getnet_terminal_id)
        self.assertEqual(payment.getnet_selectable_terminal_ids,
                         self.terminal + terminal2)
        # Sin elegir, el cobro no sale a ninguna terminal "por defecto"
        with self.assertRaises(UserError):
            payment._getnet_terminal(self.provider)

    def test_el_payload_usa_el_termcod_de_la_terminal_elegida(self):
        """El TermCod sale de la terminal elegida, no de la primera."""
        terminal2 = self._segunda_terminal()
        for terminal in (self.terminal, terminal2):
            payment = self._create_payment(getnet_terminal_id=terminal.id)
            resuelta = payment._getnet_terminal(self.provider)
            vals = payment._getnet_prepare_transaccion_vals(
                self.provider, resuelta)
            self.assertEqual(resuelta, terminal)
            self.assertEqual(vals['TermCod'], terminal.term_cod)

    def test_el_wizard_pasa_la_terminal_elegida_al_pago(self):
        """Registrar Pago: la terminal elegida viaja al account.payment."""
        terminal2 = self._segunda_terminal()
        invoice = self._create_invoice_anexo()
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({
                'journal_id': self.journal.id,
                'payment_method_line_id': self.apm_line.id,
            })
        self.assertTrue(wizard.getnet_is_getnet_journal)
        self.assertTrue(wizard.getnet_need_terminal_choice)
        self.assertFalse(wizard.getnet_terminal_id)
        wizard.getnet_terminal_id = terminal2
        vals = wizard._getnet_payment_vals()
        self.assertEqual(vals['getnet_terminal_id'], terminal2.id)

    # ------------------------------------------------------------------
    # Permisos: el flujo lo opera un contador, no un administrador
    # ------------------------------------------------------------------
    def _contador(self):
        """
        Usuario de contabilidad SIN Ajustes.

        Correr el flujo como admin no prueba nada: admin pasa cualquier ACL
        y el sudo() del código quedaría sin verificar. 19.0: el campo de
        grupos en res.users es ``group_ids``, ya no ``groups_id``.
        """
        return self.env['res.users'].create({
            'name': 'Contador Getnet',
            'login': 'contador.getnet.%s' % uuid.uuid4().hex[:8],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
            ])],
        })

    def test_el_contador_no_puede_leer_payment_provider(self):
        """
        Justifica los sudo() de los computes: payment.provider es de
        base.group_system y el contador NO lo lee. Sin sudo, abrir el form
        del pago revienta con AccessError antes de mostrar nada. Si algún
        día se le diera lectura, este test lo avisa y los sudo() podrían
        revisarse.
        """
        contador = self._contador()
        with self.assertRaises(AccessError):
            self.provider.with_user(contador).read(['code'])

    def test_el_form_del_pago_abre_para_el_contador(self):
        """
        Regresión del AccessError sobre payment.provider: los computes de
        Getnet se evalúan al cargar el form, así que si piden el proveedor
        sin sudo el contador no puede ni abrir la pantalla.
        """
        contador = self._contador()
        payment = self._create_payment().with_user(contador)
        payment.invalidate_recordset()
        datos = payment.read([
            'getnet_is_getnet_payment_line',
            'getnet_is_integrated_journal',
            'getnet_post_blocked',
            'getnet_selectable_terminal_ids',
        ])[0]
        self.assertTrue(datos['getnet_is_getnet_payment_line'])
        self.assertTrue(datos['getnet_is_integrated_journal'])
        self.assertTrue(datos['getnet_post_blocked'])
        self.assertEqual(datos['getnet_selectable_terminal_ids'],
                         self.terminal.ids)

    def test_el_contador_ve_los_flags_y_los_guards(self):
        """Los computes del form no piden permisos que el contador no tenga."""
        contador = self._contador()
        payment = self._create_payment().with_user(contador)
        payment.invalidate_recordset()
        self.assertTrue(payment.getnet_post_blocked)
        self.assertTrue(payment.getnet_is_getnet_payment_line)
        self.assertEqual(payment.getnet_selectable_terminal_ids, self.terminal)
        # El bloqueo llega como UserError (regla de negocio), no como
        # AccessError: el contador tiene permiso, lo que falta es el cobro.
        with self.assertRaises(UserError) as capturado:
            payment.action_post()
        self.assertNotIsInstance(capturado.exception, AccessError)

    def test_el_contador_confirma_y_concilia(self):
        """Camino completo con la tx ya aprobada, corrido como contador."""
        invoice = self._create_invoice_anexo()
        payment = self._create_payment(
            amount=invoice.amount_total,
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        self._create_done_tx(payment)
        contador = self._contador()
        payment.with_user(contador).action_post()
        self._assert_confirmado(payment)
        self.assertEqual(invoice.amount_residual, 0.0)

    # ------------------------------------------------------------------
    # Facturas origen: carga desde el form y conciliación
    # ------------------------------------------------------------------
    def test_facturas_origen_editables_en_el_form_del_pago(self):
        """
        El form del pago es el único lugar de la UI donde se cargan: el
        wizard «Registrar pago» postea el pago al crearlo y el guard lo
        rechaza. Sin este campo todo cobro saldría con FacturaNro=0.
        """
        arch = etree.fromstring(
            self.env['account.payment'].get_view(view_type='form')['arch'])
        nodos = arch.xpath("//field[@name='getnet_source_invoice_ids']")
        self.assertTrue(nodos, 'el campo no está en el form del pago')
        self.assertEqual(nodos[0].get('readonly'), "state != 'draft'")

    def test_confirmar_concilia_con_la_factura_origen(self):
        """Camino feliz: misma cuenta de deudores, se concilia sola."""
        invoice = self._create_invoice_anexo()
        payment = self._create_payment(
            amount=invoice.amount_total,
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        self._create_done_tx(payment)
        payment.action_post()
        self._assert_confirmado(payment)
        self.assertEqual(invoice.amount_residual, 0.0)

    def test_el_pago_en_borrador_no_tiene_asiento(self):
        """
        En 19.0 el pago dejó de ser ``_inherits`` del asiento y el asiento
        recién se genera al confirmar. Por eso los apuntes a conciliar se
        piden a ``pay.move_id`` y no a ``pay``: ``pay.line_ids`` no existe
        y la conciliación reventaría con AttributeError dentro de
        action_post, con el cobro ya hecho en el pinpad.
        """
        invoice = self._create_invoice_anexo()
        payment = self._create_payment(
            amount=invoice.amount_total,
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        self.assertFalse(payment.move_id)
        self.assertFalse(
            self.env['account.payment']._fields.get('line_ids'))
        self._create_done_tx(payment)
        payment.action_post()
        self.assertTrue(payment.move_id)
        self.assertTrue(payment._getnet_open_receivable_lines(payment.move_id)
                        or invoice.amount_residual == 0.0)

    def test_conciliacion_imposible_no_aborta_la_confirmacion(self):
        """
        Con el pago y la factura en cuentas de deudores distintas, la
        conciliación no es posible. Antes eso levantaba UserError DENTRO
        de action_post y dejaba un cobro ya aprobado en el pinpad sin
        poder confirmarse; ahora el pago se confirma y queda el aviso.
        """
        invoice = self._create_invoice_anexo()
        otra_cuenta = self.env['account.account'].create({
            'name': 'Deudores alternativos Getnet',
            'code': 'GETNREC1',
            'account_type': 'asset_receivable',
            'reconcile': True,
        })
        # El pago toma la cuenta vigente del partner al crearse, así que
        # cambiarla después de la factura las deja en cuentas distintas.
        self.partner.property_account_receivable_id = otra_cuenta
        payment = self._create_payment(
            amount=invoice.amount_total,
            getnet_source_invoice_ids=[(6, 0, invoice.ids)])
        self._create_done_tx(payment)
        payment.action_post()
        self._assert_confirmado(payment)
        self.assertEqual(invoice.amount_residual, invoice.amount_total)
        cuerpos = ' '.join(payment.message_ids.mapped('body'))
        self.assertIn(invoice.name, cuerpos)
