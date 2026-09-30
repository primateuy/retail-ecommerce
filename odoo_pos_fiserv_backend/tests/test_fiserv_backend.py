# -*- coding: utf-8 -*-
"""
Tests del flujo contable Fiserv: crear transacción (y qué pasa cuando ITD no
contesta), el hilo de consultas, reconsultar, guards de confirmar / cancelar /
borrador / rechazar, conciliación con los estados de 19.0, el contador sin
Ajustes y las vistas tal como las sirve Odoo.

Todo ITD está mockeado.
"""

import uuid
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_fiserv_backend.models import account_payment as ap_mod
from odoo.addons.odoo_pos_fiserv_core.models import fiserv_utils
from odoo.addons.odoo_pos_fiserv_core.models import payment_transaction as pt_mod
from odoo.addons.odoo_pos_fiserv_core.tests.common import _RelojDeLaboratorio

TRANSPORTE = fiserv_utils.FISERV_RC_TRANSPORTE
INICIO_OK = {'ResponseCode': '0', 'TransactionId': '7788', 'msg': 'Resultado OK'}
APROBADA = {
    'ResponseCode': '0', 'PosResponseCode': '00', 'TransactionId': '7788',
    'PosID': 'P0001', 'Ticket': '000321', 'Batch': '9', 'AuthorizationCode': 'Z9',
    'TotalAmount': '12200', 'Currency': '858', 'CardNumber': '4507990000009999',
    'Issuer': '2', 'Acquirer': '5',
}
DENEGADA = dict(APROBADA, PosResponseCode='51')


@tagged('post_install', '-at_install')
class TestFiservBackend(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Fiserv Backend Test',
            'code': 'fiserv',
            'state': 'test',
            'fiserv_url_webservice': 'https://itd.example.invalid/v2/ITDService',
            'fiserv_system_id': 'SYSFAKE0001',
        })
        cls.terminal = cls.env['fiserv.pos.terminal'].create({
            'name': 'Caja Backend', 'pos_id': 'P0001', 'payment_provider_id': cls.provider.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Backend Fiserv'})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Fiserv Test', 'code': 'FSVB', 'type': 'bank'})
        cls.provider.journal_id = cls.journal
        lines = cls.env['account.payment.method.line'].search([
            ('payment_provider_id', '=', cls.provider.id)])
        # LA CUENTA DE COBROS PENDIENTES SE FIJA A PROPÓSITO (lección del port
        # de Getnet): en 19.0 un pago cuyo método no la tiene se confirma SIN
        # asiento. Dejarlo al azar del plan de cuentas es probar la base.
        lines.write({'payment_account_id': cls._cuenta_pendiente().id})
        cls.line_in = lines.filtered(lambda l: l.payment_type == 'inbound')
        cls.line_out = lines.filtered(lambda l: l.payment_type == 'outbound')
        cls.manual_in = cls.journal.inbound_payment_method_line_ids.filtered(
            lambda l: l.code == 'manual')[:1]
        cls.tax22 = cls.env['account.tax'].create({
            'name': 'IVA 22 test fiserv', 'amount': 22.0, 'type_tax_use': 'sale'})

    @classmethod
    def _cuenta_pendiente(cls):
        cuenta = cls.env['account.account'].search([
            ('code', '=', 'FSVPEND'),
            *cls.env['account.account']._check_company_domain(cls.env.company),
        ], limit=1)
        return cuenta or cls.env['account.account'].create({
            'name': 'Fiserv cobros pendientes (test)', 'code': 'FSVPEND',
            'account_type': 'asset_current', 'reconcile': True,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_payment(self, **vals):
        base = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 122.0,
            'journal_id': self.journal.id,
            'payment_method_line_id': self.line_in.id,
            'fiserv_charge_on_pos': True,
            'fiserv_terminal_id': self.terminal.id,
        }
        base.update(vals)
        return self.env['account.payment'].create(base)

    def _create_tx(self, payment, state='done', **vals):
        tx = self.env['payment.transaction'].create(dict({
            'provider_id': self.provider.id,
            'payment_method_id': self.env.ref('odoo_pos_fiserv_core.payment_method_fiserv').id,
            'reference': 'FISERV-BK-%s' % uuid.uuid4().hex[:10],
            'amount': payment.amount,
            'currency_id': payment.currency_id.id,
            'partner_id': self.partner.id,
            'account_payment_id': payment.id,
            'transaction_origin': 'account_payment',
            'fiserv_transaction_id': '7788',
            'ticket_number': '000321',
            'pos_id': 'P0001',
        }, **vals))
        if state == 'done':
            tx._set_done()
        elif state == 'pending':
            tx._set_pending()
        payment.payment_transaction_id = tx
        return tx

    def _create_invoice(self, price=100.0):
        journal = self.env['account.journal'].search([('code', '=', 'FVTA')], limit=1) or \
            self.env['account.journal'].create({
                'name': 'Ventas Fiserv Test', 'code': 'FVTA', 'type': 'sale',
                'l10n_latam_use_documents': False,
            })
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'línea', 'quantity': 1, 'price_unit': price,
                'tax_ids': [(6, 0, self.tax22.ids)]})],
        })
        invoice.action_post()
        return invoice

    def _usuario(self, *xmlids, company=None):
        company = company or self.env.company
        return self.env['res.users'].create({
            'name': 'Usuario %s' % uuid.uuid4().hex[:6],
            'login': 'fiserv.bk.%s' % uuid.uuid4().hex[:10],
            'company_id': company.id,
            'company_ids': [(6, 0, company.ids)],
            'group_ids': [(6, 0, [self.env.ref(x).id for x in xmlids])],
        })

    def _contador(self):
        """Contabilidad SIN Ajustes: correr como admin no prueba ningún sudo."""
        return self._usuario('base.group_user', 'account.group_account_user')

    @contextmanager
    def _itd(self, inicio=None, consultas=None, sin_hilo=True):
        """ITD de laboratorio a nivel proveedor; registra el orden de los eventos."""
        eventos = []
        Provider = type(self.env['payment.provider'])
        consultas = list(consultas or [])

        def start_purchase(prov, data):
            eventos.append(('post', data))
            return dict(inicio or INICIO_OK)

        def itd_query(prov, data):
            eventos.append(('query', data))
            if len(consultas) > 1:
                return dict(consultas.pop(0))
            return dict(consultas[0]) if consultas else dict(APROBADA)

        def safe_commit(env):
            eventos.append(('commit', None))

        parches = [
            patch.object(Provider, '_fiserv_start_purchase', start_purchase),
            patch.object(Provider, '_fiserv_itd_query', itd_query),
            patch.object(Provider, '_fiserv_itd_confirm', lambda p, d: {'ResponseCode': '0'}),
            patch.object(Provider, '_fiserv_itd_reverse', lambda p, d: {'ResponseCode': '0'}),
            patch.object(fiserv_utils, 'fiserv_safe_commit', safe_commit),
            patch.object(pt_mod, 'time', _RelojDeLaboratorio(range(0, 100000, 10))),
        ]
        if sin_hilo:
            parches.append(patch.object(
                type(self.env['account.payment']), '_fiserv_start_worker_thread',
                lambda pay, tx, prov, sent, tid: eventos.append(('hilo', tid))))
        for p in parches:
            p.start()
        try:
            yield eventos
        finally:
            for p in reversed(parches):
                p.stop()

    def _crear(self, payment):
        """Crear transacción SIN assertRaises: su savepoint escondería lo consolidado."""
        try:
            payment.action_fiserv_create_transaction()
        except UserError as error:
            return error
        return None

    # ------------------------------------------------------------------
    # Crear transacción
    # ------------------------------------------------------------------
    def test_crear_transaccion_la_registra_antes_de_hablar_con_itd(self):
        """
        🔴 En 17.0 la payment.transaction recién se creaba DESPUÉS del bucle de
        consultas: si Odoo se reiniciaba a mitad, el cobro en vuelo no dejaba
        ningún registro. Ahora existe y se consolida antes del POST.
        """
        payment = self._create_payment()
        with self._itd() as eventos:
            self.assertIsNone(self._crear(payment))
        tipos = [e[0] for e in eventos]
        self.assertLess(tipos.index('commit'), tipos.index('post'),
                        'la transacción tiene que consolidarse antes del POST')
        tx = payment.payment_transaction_id
        self.assertEqual(tx.state, 'pending')
        self.assertEqual(tx.fiserv_transaction_id, '7788')
        self.assertEqual(tx.account_payment_id, payment)
        self.assertEqual(tx.pos_id, 'P0001')
        self.assertNotIn('SYSFAKE0001', tx.fiserv_complete_request)
        self.assertTrue(payment.fiserv_async_terminal_pending)
        self.assertIn(('hilo', '7788'), eventos)
        self.assertEqual(payment.state, 'draft')

    def test_un_fallo_de_transporte_al_iniciar_no_es_un_rechazo(self):
        """
        🔴 DL-6 del lado Fiserv: en 17.0 un 5xx del POST inicial se guardaba
        como transacción `error` («ITD rechazó el inicio») y un timeout salía
        como traceback. El pedido pudo haber llegado: queda pendiente, marcada
        para verificar, y el pago NO se puede volver a cobrar.
        """
        payment = self._create_payment()
        with self._itd(inicio={'ResponseCode': TRANSPORTE, 'msg': 'HTTP 504'}):
            error = self._crear(payment)
        self.assertIsNotNone(error)
        self.assertIn('NO vuelva a cobrar', str(error))
        tx = payment.payment_transaction_id
        self.assertEqual(tx.state, 'pending')
        self.assertTrue(tx.fiserv_requiere_conciliacion)
        self.assertFalse(payment.fiserv_async_terminal_pending)
        self.assertTrue(payment.fiserv_tx_is_pending)
        self.assertFalse(payment.fiserv_tx_can_requery,
                         'sin TransactionId no hay a quién reconsultar: el botón no se ofrece')
        with self._itd(), self.assertRaisesRegex(UserError, 'NO vuelva a cobrar'):
            payment.action_fiserv_create_transaction()

    def test_un_rechazo_de_itd_si_cierra_la_transaccion(self):
        """ITD contestó que no: nada en el pinpad, `error`, y se puede reintentar."""
        payment = self._create_payment()
        with self._itd(inicio={'ResponseCode': '100', 'TransactionId': '0'}):
            error = self._crear(payment)
        self.assertIn('ITD rechazó el inicio', str(error))
        self.assertEqual(payment.payment_transaction_id.state, 'error')
        self.assertFalse(payment.fiserv_tx_is_pending)
        with self._itd() as eventos:
            self.assertIsNone(self._crear(payment))
        self.assertIn('post', [e[0] for e in eventos])

    def test_proveedor_deshabilitado_no_cobra(self):
        payment = self._create_payment()
        self.provider.state = 'disabled'
        with self._itd() as eventos, self.assertRaisesRegex(UserError, 'deshabilitado'):
            payment.action_fiserv_create_transaction()
        self.assertFalse(eventos)

    # ------------------------------------------------------------------
    # Hilo de consultas
    # ------------------------------------------------------------------
    def _hilo(self, payment, consultas, sent=None):
        tx = self._create_tx(payment, state='pending')
        sent = sent or {'PosID': 'P0001', 'SystemId': 'X', 'Branch': '', 'ClientAppId': '1',
                        'UserId': '2', 'Amount': '12200'}
        with self._itd(consultas=consultas):
            payment._fiserv_worker_inner(tx, self.provider, sent, '7788')
        return tx

    def test_hilo_aprobada_no_confirma_el_pago(self):
        payment = self._create_payment()
        tx = self._hilo(payment, [{'ResponseCode': '10'}, APROBADA])
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.ticket_number, '000321')
        self.assertEqual(payment.state, 'draft', 'nunca auto-post')
        self.assertTrue(payment.fiserv_tx_is_done)
        self.assertFalse(payment.pos_integrated_post_blocked)
        self.assertIn('Pulse «Confirmar»', payment.message_ids[0].body)

    def test_hilo_denegada_no_habilita_confirmar(self):
        payment = self._create_payment()
        tx = self._hilo(payment, [DENEGADA])
        self.assertEqual(tx.state, 'error')
        self.assertTrue(payment.pos_integrated_post_blocked)
        with self.assertRaises(UserError):
            payment.action_post()

    def test_hilo_sin_respuesta_hasta_el_tope_queda_pendiente(self):
        payment = self._create_payment()
        tx = self._hilo(payment, [{'ResponseCode': TRANSPORTE, 'msg': 'HTTP 502'}])
        self.assertEqual(tx.state, 'pending')
        self.assertTrue(tx.fiserv_requiere_conciliacion)
        self.assertTrue(payment.fiserv_tx_is_pending)

    def test_hilo_void_sin_original_reintenta_como_refund(self):
        """posResponseCode 25 tras un void aceptado: se reejecuta como refund."""
        original = self._create_tx(self._create_payment(), state='done')
        devolucion = self._create_payment(
            payment_type='outbound', payment_method_line_id=self.line_out.id,
            fiserv_original_transaction_id=original.id, amount=original.amount)
        tx = self._create_tx(devolucion, state='pending', amount=-original.amount)
        void = {'PosID': 'P0001', 'SystemId': 'X', 'Branch': '', 'ClientAppId': '1',
                'UserId': '2', 'TicketNumber': '000321'}
        Provider = type(self.env['payment.provider'])
        refund_resp = {'ResponseCode': '0', 'TransactionId': '9911'}
        with self._itd(consultas=[{'ResponseCode': '0', 'PosResponseCode': '25'},
                                  dict(APROBADA, TransactionId='9911')]), \
                patch.object(Provider, '_fiserv_itd_post',
                             lambda p, path, data, label, **kw: dict(refund_resp)):
            devolucion._fiserv_worker_inner(tx, self.provider, void, '7788')
        self.assertEqual(tx.fiserv_transaction_id, '9911')
        self.assertIn('OriginalTransactionDateyyMMdd', tx.fiserv_complete_request)
        self.assertEqual(tx.state, 'done')
        self.assertLess(tx.amount, 0, 'una devolución se guarda en negativo')

    def test_el_hilo_abre_su_cursor_con_la_api_de_19(self):
        """
        REGRESIÓN que Getnet ya pagó: en 19.0 `odoo.registry` no existe y el
        hilo nunca corre en la suite, así que un error ahí aparece recién en
        vivo. Se ejecuta el cuerpo de verdad con el Registry sustituido para
        que reuse el cursor del test.
        """
        payment = self._create_payment()
        tx = self._create_tx(payment, state='pending')
        payment.fiserv_async_terminal_pending = True
        cursor = self.env.cr

        class _RegistroFalso:
            @contextmanager
            def cursor(self):
                yield cursor

        llamadas = []
        with patch('odoo.modules.registry.Registry', lambda dbname: _RegistroFalso()), \
                patch.object(type(payment), '_fiserv_worker_inner',
                             lambda *a, **k: llamadas.append(True)), \
                patch.object(fiserv_utils, 'fiserv_safe_commit', lambda env: None):
            payment._fiserv_worker_thread_entry(
                self.env.cr.dbname, self.env.uid, payment.id, tx.id,
                self.provider.id, {'PosID': 'P0001'}, '7788')
        self.assertTrue(llamadas, 'el cuerpo del hilo no llegó a correr')
        payment.invalidate_recordset()
        self.assertFalse(payment.fiserv_async_terminal_pending,
                         'el finally tiene que liberar el pago')

    def test_si_el_hilo_explota_la_transaccion_sigue_pendiente(self):
        payment = self._create_payment()
        tx = self._create_tx(payment, state='pending')
        payment.fiserv_async_terminal_pending = True
        rollbacks = []

        class _CursorProxy:
            """El cursor del test, sin dejar que el rollback lo vacíe."""
            def __init__(self, cr):
                self._cr = cr

            def rollback(self):
                rollbacks.append(True)

            def __getattr__(self, nombre):
                return getattr(self._cr, nombre)

        proxy = _CursorProxy(self.env.cr)

        class _RegistroFalso:
            @contextmanager
            def cursor(self):
                yield proxy

        def explota(*a, **k):
            raise RuntimeError('ITD devolvió basura')

        with patch('odoo.modules.registry.Registry', lambda dbname: _RegistroFalso()), \
                patch.object(type(payment), '_fiserv_worker_inner', explota), \
                patch.object(fiserv_utils, 'fiserv_safe_commit', lambda env: None), \
                patch('odoo.api.Environment', lambda cr, uid, ctx: self.env(user=uid)):
            payment._fiserv_worker_thread_entry(
                self.env.cr.dbname, self.env.uid, payment.id, tx.id,
                self.provider.id, {'PosID': 'P0001'}, '7788')
        self.assertTrue(rollbacks)
        payment.invalidate_recordset()
        self.assertFalse(payment.fiserv_async_terminal_pending)
        self.assertEqual(tx.state, 'pending')
        self.assertTrue(payment.fiserv_tx_is_pending, 'queda a la vista para reconsultar')

    # ------------------------------------------------------------------
    # Reconsultar y verificar
    # ------------------------------------------------------------------
    def _reconsultar(self, payment, respuesta):
        with self._itd(consultas=[respuesta]):
            payment.action_fiserv_requery()

    def test_reconsultar_con_resultado_final(self):
        payment = self._create_payment()
        tx = self._create_tx(payment, state='pending')
        self.assertTrue(payment.fiserv_tx_can_requery)
        self._reconsultar(payment, APROBADA)
        self.assertEqual(tx.state, 'done')
        self.assertTrue(payment.fiserv_tx_is_done)

    def test_reconsultar_en_curso_sigue_pendiente(self):
        payment = self._create_payment()
        tx = self._create_tx(payment, state='pending')
        self._reconsultar(payment, {'ResponseCode': '10'})
        self.assertEqual(tx.state, 'pending')
        self.assertFalse(tx.fiserv_requiere_conciliacion)

    def test_reconsultar_sin_resultado_nunca_da_por_fallido(self):
        """«No existe transacción» para una consulta vieja NO es un rechazo."""
        payment = self._create_payment()
        tx = self._create_tx(payment, state='pending')
        for respuesta in ({'ResponseCode': TRANSPORTE}, {'ResponseCode': '110'}):
            self._reconsultar(payment, respuesta)
            self.assertEqual(tx.state, 'pending')
            self.assertTrue(tx.fiserv_requiere_conciliacion)

    def test_reconsultar_respeta_un_hilo_vivo(self):
        payment = self._create_payment()
        self._create_tx(payment, state='pending')
        payment.write({'fiserv_async_terminal_pending': True,
                       'fiserv_async_started_at': fields.Datetime.now()})
        with self._itd(), self.assertRaisesRegex(UserError, 'sigue en curso'):
            payment.action_fiserv_requery()
        # Un «en curso» de un proceso que murió hace rato sí se puede reconsultar.
        payment.fiserv_async_started_at = fields.Datetime.now() - timedelta(hours=2)
        self._reconsultar(payment, APROBADA)
        self.assertFalse(payment.fiserv_async_terminal_pending)
        self.assertTrue(payment.fiserv_tx_is_done)

    def test_verificada_sin_cobro_libera_el_pago(self):
        payment = self._create_payment()
        tx = self._create_tx(payment, state='draft', fiserv_transaction_id=False)
        tx._fiserv_persist_query_result({'ResponseCode': TRANSPORTE, 'msg': 'HTTP 504'})
        self.assertTrue(payment.fiserv_tx_is_pending)
        payment.with_user(self._contador()).action_fiserv_mark_verified()
        self.assertEqual(tx.state, 'cancel')
        self.assertFalse(payment.fiserv_tx_is_pending)
        with self._itd() as eventos:
            self.assertIsNone(self._crear(payment))
        self.assertIn('post', [e[0] for e in eventos])

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def test_confirmar_bloqueado_sin_tx_aprobada(self):
        with self.assertRaises(UserError):
            self._create_payment().action_post()

    def test_confirmar_bloqueado_con_tx_pendiente(self):
        payment = self._create_payment()
        self._create_tx(payment, state='pending')
        with self.assertRaisesRegex(UserError, 'sin resultado'):
            payment.action_post()

    def test_confirmar_con_tx_aprobada(self):
        payment = self._create_payment()
        self._create_tx(payment)
        payment.action_post()
        self.assertIn(payment.state, ap_mod.FISERV_PAYMENT_CONFIRMADO)

    def test_estados_confirmados_existen_en_el_core(self):
        """Si el core renombra estados, esto avisa (en 17→19 desapareció 'posted')."""
        estados = dict(self.env['account.payment']._fields['state'].selection)
        for estado in ap_mod.FISERV_PAYMENT_CONFIRMADO:
            self.assertIn(estado, estados)
        self.assertNotIn('posted', estados)

    def test_cancelar_borrador_y_rechazar_bloqueados_con_tx_aprobada(self):
        payment = self._create_payment()
        self._create_tx(payment)
        payment.action_post()
        for accion in ('action_cancel', 'action_draft', 'action_reject'):
            with self.assertRaises(UserError, msg=accion):
                getattr(payment, accion)()

    def test_un_pago_manual_del_mismo_diario_no_se_bloquea(self):
        """
        En 19.0, al habilitar el proveedor Odoo le asigna el primer diario
        bancario. La regla de 17.0 («diario integrado ⇒ bloquear») dejaba
        TODOS los pagos manuales de ese banco sin poder confirmarse.
        """
        self.assertTrue(self.manual_in, 'el diario de prueba no tiene método manual')
        payment = self._create_payment(payment_method_line_id=self.manual_in.id,
                                       fiserv_charge_on_pos=False, fiserv_terminal_id=False)
        self.assertTrue(payment.fiserv_is_integrated_journal)
        self.assertFalse(payment.pos_integrated_post_blocked)
        payment.action_post()
        self.assertIn(payment.state, ap_mod.FISERV_PAYMENT_CONFIRMADO)

    def test_el_onchange_desmarca_al_cambiar_de_metodo(self):
        """En 17.0 el check quedaba pegado al pasar a otro método."""
        payment = self._create_payment()
        payment.payment_method_line_id = self.manual_in
        payment._onchange_fiserv_auto_charge_integrated_journal()
        self.assertFalse(payment.fiserv_charge_on_pos)
        self.assertFalse(payment.fiserv_terminal_id)
        payment.payment_method_line_id = self.line_in
        payment._onchange_fiserv_auto_charge_integrated_journal()
        self.assertTrue(payment.fiserv_charge_on_pos)
        self.assertEqual(payment.fiserv_terminal_id, self.terminal)

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def test_payload_con_una_factura(self):
        invoice = self._create_invoice()
        payment = self._create_payment(
            amount=invoice.amount_total, fiserv_source_invoice_ids=[(6, 0, invoice.ids)])
        data = self.provider._prepare_fiserv_itd_payload_for_account_payment(payment)
        self.assertEqual(data['Amount'], '12200')
        self.assertEqual(data['PosID'], 'P0001')
        self.assertEqual(data['TaxRefund'], 2200)
        self.assertEqual(data['TaxAmount'], '2200')
        self.assertEqual(len(data['InvoiceNumber']), 7)
        self.assertTrue(data['NeedToReadCard'])

    def test_payload_sin_factura_usa_el_pago(self):
        payment = self._create_payment()
        data = self.provider._prepare_fiserv_itd_payload_for_account_payment(payment)
        self.assertEqual(data['InvoiceNumber'], str(payment.id).zfill(7))
        self.assertEqual(data['TaxRefund'], 0)

    def test_devolucion_exige_la_original(self):
        payment = self._create_payment(payment_type='outbound',
                                       payment_method_line_id=self.line_out.id)
        with self._itd(), self.assertRaisesRegex(UserError, 'original'):
            payment.action_fiserv_create_transaction()

    def test_devolucion_con_lote_cerrado_va_directo_a_refund(self):
        original = self._create_tx(self._create_payment(), state='done', batch_number='9')
        devolucion = self._create_payment(
            payment_type='outbound', payment_method_line_id=self.line_out.id,
            fiserv_original_transaction_id=original.id, amount=original.amount)
        rutas = []
        Provider = type(self.env['payment.provider'])

        def itd_post(prov, path, data, label, **kw):
            rutas.append(path)
            if path == '/processCurrentTransactionsBatchQuery':
                return {'ResponseCode': '0', 'Transactions': []}
            return {'ResponseCode': '0', 'TransactionId': '5555'}

        with self._itd(), patch.object(Provider, '_fiserv_itd_post', itd_post):
            self.assertIsNone(self._crear(devolucion))
        self.assertEqual(rutas, ['/processCurrentTransactionsBatchQuery',
                                 '/processFinancialPurchaseRefund'])
        tx = devolucion.payment_transaction_id
        self.assertEqual(tx.fiserv_transaction_id, '5555')
        self.assertLess(tx.amount, 0)

    def test_devolucion_void_transporte_no_dispara_refund(self):
        """El void pudo haber llegado: mandar además un refund devolvería dos veces."""
        original = self._create_tx(self._create_payment(), state='done')
        devolucion = self._create_payment(
            payment_type='outbound', payment_method_line_id=self.line_out.id,
            fiserv_original_transaction_id=original.id, amount=original.amount)
        rutas = []
        Provider = type(self.env['payment.provider'])

        def itd_post(prov, path, data, label, **kw):
            rutas.append(path)
            if path == '/processCurrentTransactionsBatchQuery':
                return {'ResponseCode': '999'}
            return {'ResponseCode': TRANSPORTE, 'msg': 'timeout'}

        with self._itd(), patch.object(Provider, '_fiserv_itd_post', itd_post):
            error = self._crear(devolucion)
        self.assertIn('NO vuelva a cobrar', str(error))
        self.assertNotIn('/processFinancialPurchaseRefund', rutas)
        self.assertEqual(devolucion.payment_transaction_id.state, 'pending')

    # ------------------------------------------------------------------
    # Conciliación (estados de 19.0)
    # ------------------------------------------------------------------
    def test_confirmar_concilia_con_la_factura_origen(self):
        """En 17.0 filtraba state == 'posted', que en 19.0 no existe: nunca conciliaba."""
        invoice = self._create_invoice()
        payment = self._create_payment(
            amount=invoice.amount_total, fiserv_source_invoice_ids=[(6, 0, invoice.ids)])
        self.assertFalse(payment.move_id, 'en 19.0 el borrador no tiene asiento')
        self._create_tx(payment)
        payment.action_post()
        self.assertTrue(payment.move_id)
        self.assertEqual(invoice.amount_residual, 0.0)

    def test_conciliacion_imposible_no_aborta_la_confirmacion(self):
        invoice = self._create_invoice()
        otra = self.env['account.account'].create({
            'name': 'Deudores alternativos Fiserv', 'code': 'FSVREC1',
            'account_type': 'asset_receivable', 'reconcile': True})
        self.partner.property_account_receivable_id = otra
        payment = self._create_payment(
            amount=invoice.amount_total, fiserv_source_invoice_ids=[(6, 0, invoice.ids)])
        self._create_tx(payment)
        payment.action_post()
        self.assertIn(payment.state, ap_mod.FISERV_PAYMENT_CONFIRMADO)
        self.assertEqual(invoice.amount_residual, invoice.amount_total)
        self.assertIn(invoice.name, ' '.join(payment.message_ids.mapped('body')))

    # ------------------------------------------------------------------
    # Permisos: lo opera un contador, no un administrador
    # ------------------------------------------------------------------
    def test_el_contador_no_lee_payment_provider(self):
        """Justifica los sudo() acotados: si algún día lo lee, este test avisa."""
        with self.assertRaises(AccessError):
            self.provider.with_user(self._contador()).read(['code'])

    def test_el_form_del_pago_abre_para_el_contador(self):
        contador = self._contador()
        payment = self._create_payment().with_user(contador)
        payment.invalidate_recordset()
        datos = payment.read([
            'fiserv_is_fiserv_payment_line', 'fiserv_is_integrated_journal',
            'pos_integrated_post_blocked', 'fiserv_selectable_terminal_ids',
            'fiserv_payment_tx_provider_code', 'fiserv_tx_is_pending',
        ])[0]
        self.assertTrue(datos['fiserv_is_fiserv_payment_line'])
        self.assertTrue(datos['pos_integrated_post_blocked'])
        self.assertEqual(datos['fiserv_selectable_terminal_ids'], self.terminal.ids)
        arch = payment.get_view(view_type='form')['arch']
        self.assertIn('action_fiserv_create_transaction', arch)

    def test_el_contador_elige_la_transaccion_original(self):
        """El dominio no atraviesa payment.provider, que el contador no lee."""
        original = self._create_tx(self._create_payment(), state='done')
        dominio = self.env['account.payment']._fields['fiserv_original_transaction_id'].domain
        dominio = dominio.replace("'=', company_id)", "'=', %d)" % self.env.company.id)
        encontradas = self.env['payment.transaction'].with_user(self._contador()).search(eval(dominio))
        self.assertIn(original, encontradas)

    def test_el_contador_cobra_confirma_y_concilia(self):
        """Camino completo como contador: crear transacción, hilo, confirmar."""
        contador = self._contador()
        invoice = self._create_invoice()
        payment = self._create_payment(
            amount=invoice.amount_total, fiserv_source_invoice_ids=[(6, 0, invoice.ids)])
        como_contador = payment.with_user(contador)
        with self._itd() as eventos:
            self.assertIsNone(self._crear(como_contador))
        tx = payment.payment_transaction_id
        self.assertEqual(tx.state, 'pending')
        # El hilo entero —cursor propio, cuerpo y finally— con el uid del contador.
        cursor = self.env.cr

        class _RegistroFalso:
            @contextmanager
            def cursor(self):
                yield cursor

        with self._itd(consultas=[APROBADA]), \
                patch('odoo.modules.registry.Registry', lambda dbname: _RegistroFalso()):
            payment._fiserv_worker_thread_entry(
                self.env.cr.dbname, contador.id, payment.id, tx.id, self.provider.id,
                eventos[1][1], '7788')
        payment.invalidate_recordset()
        tx.invalidate_recordset()
        self.assertEqual(tx.state, 'done')
        self.assertFalse(payment.fiserv_async_terminal_pending)
        como_contador.action_post()
        self.assertIn(payment.state, ap_mod.FISERV_PAYMENT_CONFIRMADO)
        self.assertEqual(invoice.amount_residual, 0.0)

    def test_sin_facturacion_no_se_opera_la_terminal(self):
        """Los botones son RPC-alcanzables: el guard está en el método."""
        auditor = self._usuario('base.group_user', 'account.group_account_readonly')
        payment = self._create_payment()
        with self._itd() as eventos:
            for metodo in ('action_fiserv_create_transaction', 'action_fiserv_requery'):
                with self.assertRaises(AccessError, msg=metodo):
                    getattr(payment.with_user(auditor), metodo)()
        self.assertFalse(eventos)

    def test_el_borrador_no_se_escribe_saltando_reglas(self):
        """
        🔴 17.0 escribía en sudo CUALQUIER borrador si el usuario tenía ACL de
        escritura: se salteaba las reglas por registro, incluidas las
        multicompañía. Un contador de una compañía podía editar borradores de
        otra.
        """
        otra = self.env['res.company'].create({'name': 'Otra compañía Fiserv'})
        journal = self.env['account.journal'].with_company(otra).create({
            'name': 'Banco otra', 'code': 'BOTR', 'type': 'bank', 'company_id': otra.id})
        # La compañía nueva no tiene plan: se le da la cuenta pendiente a mano.
        pendiente = self.env['account.account'].with_company(otra).create({
            'name': 'Pendiente otra', 'code': 'OTRPEND', 'account_type': 'asset_current',
            'reconcile': True, 'company_ids': [(6, 0, otra.ids)]})
        journal.inbound_payment_method_line_ids.payment_account_id = pendiente
        ajeno = self.env['account.payment'].with_company(otra).create({
            'payment_type': 'inbound', 'partner_type': 'customer',
            'partner_id': self.partner.id, 'amount': 10.0, 'journal_id': journal.id,
        })
        contador = self._contador()
        with self.assertRaises(AccessError):
            ajeno.with_user(contador).write({'amount': 999.0})

    # ------------------------------------------------------------------
    # Vistas servidas
    # ------------------------------------------------------------------
    def _boton(self, arch, nombre):
        nodos = etree.fromstring(arch).xpath("//header/button[@name='%s']" % nombre)
        self.assertTrue(nodos, nombre)
        return nodos[0].get('invisible') or ''

    def test_los_bloqueos_se_suman_sin_pisar_los_ajenos(self):
        """
        El flag de borrador que en 17.0 pisaba l10n_uy_einvoice_base: ahora el
        término Fiserv se SUMA al de einvoice en el arch servido.
        """
        arch = self.env['account.payment'].with_user(self._contador()).get_view(view_type='form')['arch']
        self.assertIn('pos_integrated_post_blocked', self._boton(arch, 'action_post'))
        self.assertIn('pos_integrated_cancel_blocked', self._boton(arch, 'action_cancel'))
        self.assertIn('pos_integrated_cancel_blocked', self._boton(arch, 'action_reject'))
        borrador = self._boton(arch, 'action_draft')
        self.assertIn('pos_integrated_draft_blocked', borrador)
        self.assertIn('cfe_emitido', borrador, 'el término de einvoice se perdió')
        self.assertNotIn('show_reset_to_draft_button', arch)

    def test_lo_que_precarga_la_devolucion_se_guarda(self):
        """
        amount / partner / moneda quedan readonly con la transacción original
        elegida, y el cliente web no guarda un campo readonly: sin force_save
        la devolución se guardaba en $0.00 (visto en las capturas del manual).
        """
        arch = etree.fromstring(self.env['account.payment'].get_view(view_type='form')['arch'])
        for campo in ('amount', 'partner_id', 'currency_id', 'fiserv_charge_on_pos'):
            nodo = arch.xpath("//sheet//field[@name='%s']" % campo)[0]
            self.assertEqual(nodo.get('force_save'), '1', campo)
        facturar = arch.xpath("//header/button[@name='facturar']")[0].get('invisible')
        self.assertIn('fiserv_is_fiserv_payment_line', facturar)

    # ------------------------------------------------------------------
    # Factura y wizard
    # ------------------------------------------------------------------
    def test_pagar_desde_la_factura_solo_con_proveedor_habilitado(self):
        invoice = self._create_invoice()
        Provider = self.env['payment.provider'].sudo()
        Provider.search([('code', '=', 'fiserv')]).write({'state': 'disabled'})
        invoice.invalidate_recordset(['fiserv_register_enabled'])
        self.assertFalse(invoice.fiserv_register_enabled,
                         'con Fiserv apagado la factura queda como la dejó Odoo')
        self.provider.state = 'test'
        invoice.invalidate_recordset(['fiserv_register_enabled'])
        self.assertTrue(invoice.fiserv_register_enabled)
        accion = invoice.with_user(self._contador()).action_fiserv_register_payment()
        self.assertEqual(accion['res_model'], 'account.payment')
        ctx = accion['context']
        self.assertEqual(ctx['default_fiserv_source_invoice_ids'], [(6, 0, invoice.ids)])
        self.assertEqual(ctx['default_memo'], invoice.name)
        self.assertEqual(ctx['default_amount'], invoice.amount_residual)

    def test_el_wizard_no_confirma_un_cobro_fiserv(self):
        invoice = self._create_invoice()
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({
                'journal_id': self.journal.id,
                'payment_method_line_id': self.line_in.id,
            })
        self.assertTrue(wizard.fiserv_is_fiserv_journal)
        with self.assertRaisesRegex(UserError, 'Pagar'):
            wizard.action_create_payments()
