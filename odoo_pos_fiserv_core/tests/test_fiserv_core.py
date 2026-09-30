# -*- coding: utf-8 -*-
"""
Tests del core Fiserv ITD: lo que crea la instalación, el transporte HTTP
(qué es rechazo y qué es «no sé»), el bucle de consultas, la persistencia del
resultado, permisos y el aviso de runtime.

Todo el transporte está mockeado: no se invoca ITD real.
"""

import json
import uuid
from unittest.mock import patch

import requests

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_fiserv_core.models import fiserv_utils
from odoo.addons.odoo_pos_fiserv_core.models import payment_provider as pp_mod
from odoo.addons.odoo_pos_fiserv_core.models import payment_transaction as pt_mod
from odoo.addons.odoo_pos_fiserv_core.tests.common import (
    TIMEOUT,
    _RelojDeLaboratorio,
    post_secuencial,
    respuesta_http,
)

TRANSPORTE = fiserv_utils.FISERV_RC_TRANSPORTE
SYSTEM_ID_FALSO = 'SYSFAKE9876'  # inventado: el real va SOLO en la base del cliente

APROBADA = {
    'ResponseCode': '0',
    'PosResponseCode': '00',
    'TransactionId': '4455',
    'PosID': 'P0001',
    'Ticket': '000123',
    'Batch': '7',
    'AuthorizationCode': 'A1B2',
    'Merchant': '99887766',
    'TotalAmount': '10000',
    'Currency': '858',
    'CardNumber': '4507990000001234',
    'Issuer': '2',
    'Acquirer': '5',
    'Quota': '1',
    'TransactionDate': '300926',
    'TransactionHour': '1015',
}


class _DriverFalso:
    """
    Driver ITD de laboratorio: contesta las consultas en orden y registra
    confirm y reverse. Cumple el contrato que usa `_fiserv_run_query_loop`.
    """

    def __init__(self, consultas, confirm=None, reverse=None):
        self.consultas = list(consultas)
        self.confirm = confirm or {'ResponseCode': '0'}
        self.reverse = reverse or {'ResponseCode': '0'}
        self.confirmados = []
        self.revertidos = []

    def ensure_one(self):
        return self

    def _fiserv_timestamp(self):
        return '20260930101500000'

    def _fiserv_itd_query(self, data):
        if len(self.consultas) > 1:
            return dict(self.consultas.pop(0))
        return dict(self.consultas[0])

    def _fiserv_itd_confirm(self, data):
        self.confirmados.append(data)
        return dict(self.confirm)

    def _fiserv_itd_reverse(self, data):
        self.revertidos.append(data)
        return dict(self.reverse)


@tagged('post_install', '-at_install')
class TestFiservCore(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Fiserv Test',
            'code': 'fiserv',
            'state': 'test',
            'fiserv_url_webservice': 'https://itd.example.invalid/v2/ITDService',
            'fiserv_system_id': SYSTEM_ID_FALSO,
            'fiserv_client_app_id': '1',
        })
        cls.terminal = cls.env['fiserv.pos.terminal'].create({
            'name': 'Caja 1',
            'pos_id': 'P0001',
            'payment_provider_id': cls.provider.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Fiserv'})
        cls.method = cls.env.ref('odoo_pos_fiserv_core.payment_method_fiserv')
        cls.uyu = cls.env.ref('base.UYU')
        cls.query_base = {
            'PosID': 'P0001', 'SystemId': SYSTEM_ID_FALSO, 'Branch': '',
            'ClientAppId': '1', 'UserId': '2',
            'TransactionDateTimeyyyyMMddHHmmssSSS': '', 'TransactionId': '4455',
        }

    def _create_tx(self, **vals):
        base = {
            'provider_id': self.provider.id,
            'payment_method_id': self.method.id,
            'reference': 'FISERV-TEST-%s' % uuid.uuid4().hex[:12],
            'amount': 100.0,
            'currency_id': self.uyu.id,
            'partner_id': self.partner.id,
            'fiserv_transaction_id': '4455',
        }
        base.update(vals)
        return self.env['payment.transaction'].create(base)

    def _run_loop(self, driver, reloj, original=None, **kwargs):
        with patch.object(pt_mod, 'time', _RelojDeLaboratorio(reloj)):
            return self.env['payment.transaction']._fiserv_run_query_loop(
                driver, dict(self.query_base), '4455',
                original_purchase_data=original, **kwargs)

    def _usuario(self, *xmlids):
        return self.env['res.users'].create({
            'name': 'Usuario %s' % uuid.uuid4().hex[:6],
            'login': 'fiserv.%s' % uuid.uuid4().hex[:10],
            'group_ids': [(6, 0, [self.env.ref(x).id for x in xmlids])],
        })

    # ------------------------------------------------------------------
    # Lo que crea la instalación
    # ------------------------------------------------------------------
    def test_la_instalacion_crea_el_proveedor(self):
        """
        En 17.0 lo creaba un post_init_hook, sin xmlid en los datos. Ahora
        está en data con el patrón de los `payment_*` del core.
        """
        provider = self.env.ref('odoo_pos_fiserv_core.payment_provider_fiserv')
        self.assertEqual(provider.code, 'fiserv')
        self.assertTrue(provider.module_id,
                        'sin module_id, Odoo no lo copia al crear una compañía nueva')
        self.assertEqual(provider.module_id.name, 'odoo_pos_fiserv_core')

    def test_el_proveedor_nace_apagado_y_sin_credenciales(self):
        """
        Un proveedor activo con credenciales vacías es un medio de cobro que
        parece disponible y no cobra. En 17.0 nacía en `test`.
        """
        provider = self.env.ref('odoo_pos_fiserv_core.payment_provider_fiserv').sudo()
        self.assertEqual(provider.state, 'disabled')
        self.assertFalse(provider.fiserv_url_webservice)
        self.assertFalse(provider.fiserv_system_id)
        self.assertFalse(provider.fiserv_branch)
        self.assertFalse(provider.fiserv_is_multiple)
        self.assertFalse(provider.allow_tokenization)

    def test_una_compania_nueva_recibe_su_propio_proveedor_apagado(self):
        """
        Comportamiento real de 19.0 (`payment/models/res_company.create`):
        los proveedores instalados se copian a cada compañía NUEVA. Las que
        ya existían al instalar no reciben ninguno — está en la guía.
        """
        Provider = self.env['payment.provider'].sudo()
        nueva = self.env['res.company'].create({'name': 'Cia Fiserv Test'})
        copia = Provider.search([('code', '=', 'fiserv'), ('company_id', '=', nueva.id)])
        self.assertEqual(len(copia), 1, 'la compañía nueva se quedó sin proveedor')
        self.assertEqual(copia.state, 'disabled')
        self.assertFalse(copia.fiserv_system_id)
        self.assertFalse(copia.fiserv_terminal_ids, 'las terminales no se copian')

    def test_el_metodo_de_pago_no_se_ofrece_en_checkout(self):
        """Cobra en un pinpad: ni método activo ni enlazado al proveedor."""
        provider = self.env.ref('odoo_pos_fiserv_core.payment_provider_fiserv')
        self.assertFalse(self.method.active)
        self.assertFalse(provider.payment_method_ids)
        self.assertTrue(self.env.ref('odoo_pos_fiserv_core.account_payment_method_fiserv'))
        self.assertTrue(self.env.ref('odoo_pos_fiserv_core.account_payment_method_fiserv_outbound'))

    def test_habilitar_crea_las_dos_lineas_con_cuenta_pendiente(self):
        """
        Al asignarle diario, el proveedor deja UNA línea de cobro y UNA de
        devolución. 19.0: con cuenta de cobros pendientes, porque un pago
        cuyo método no la tiene se confirma SIN asiento, y sin asiento no hay
        nada que conciliar con la factura.
        """
        journal = self.env['account.journal'].create({
            'name': 'Fiserv test', 'code': 'FSVT', 'type': 'bank'})
        self.provider.journal_id = journal
        lines = self.env['account.payment.method.line'].search([
            ('payment_provider_id', '=', self.provider.id)])
        self.assertEqual(sorted(lines.mapped('payment_type')), ['inbound', 'outbound'])
        self.assertEqual(lines.journal_id, journal)
        for line in lines:
            self.assertTrue(line.payment_account_id,
                            'línea %s sin cuenta pendiente' % line.payment_type)
        # Idempotente: reasignar el mismo diario no duplica.
        self.provider._ensure_payment_method_line()
        self.assertEqual(self.env['account.payment.method.line'].search_count([
            ('payment_provider_id', '=', self.provider.id)]), 2)

    def test_proveedor_deshabilitado_o_sin_datos_no_cobra(self):
        provider = self.env.ref('odoo_pos_fiserv_core.payment_provider_fiserv').sudo()
        with self.assertRaises(UserError):
            provider._fiserv_check_ready()
        provider.state = 'test'
        with self.assertRaisesRegex(UserError, 'SystemId'):
            provider._fiserv_check_ready()
        self.provider._fiserv_check_ready()

    # ------------------------------------------------------------------
    # Transporte: rechazo vs «no sé»
    # ------------------------------------------------------------------
    def _post(self, *respuestas):
        post, llamadas = post_secuencial(*respuestas)
        with patch.object(fiserv_utils.requests, 'post', post):
            resp = self.provider._fiserv_itd_post('/processFinancialPurchase', {'PosID': 'P0001'}, 't')
        return resp, llamadas

    def test_timeout_es_transporte_no_rechazo(self):
        """
        🔴 En 17.0 un timeout no se capturaba (traceback al usuario) y un 5xx
        se guardaba como transacción `error`. Los dos son «no sé»: el pedido
        pudo haber llegado y haber un cobro vivo en el pinpad.
        """
        resp, _ = self._post(TIMEOUT)
        self.assertEqual(resp['ResponseCode'], TRANSPORTE)

    def test_conexion_caida_es_transporte(self):
        resp, _ = self._post(requests.ConnectionError('conexión rechazada'))
        self.assertEqual(resp['ResponseCode'], TRANSPORTE)

    def test_http_5xx_es_transporte(self):
        for status in (500, 502, 503, 504):
            resp, _ = self._post(respuesta_http(status, texto='Bad gateway'))
            self.assertEqual(resp['ResponseCode'], TRANSPORTE, status)

    def test_http_4xx_es_rechazo(self):
        """ITD contestó que no: ahí no hay nada en el pinpad."""
        resp, _ = self._post(respuesta_http(400, texto='campo inválido'))
        self.assertEqual(resp['ResponseCode'], '999')

    def test_http_200_no_json_es_transporte(self):
        resp, _ = self._post(respuesta_http(200, texto='<html>proxy</html>'))
        self.assertEqual(resp['ResponseCode'], TRANSPORTE)

    def test_http_200_normaliza_codigos(self):
        resp, _ = self._post(respuesta_http(200, {'ResponseCode': 0, 'TransactionId': 4455}))
        self.assertEqual(resp['ResponseCode'], '0')
        self.assertEqual(resp['TransactionId'], '4455')
        self.assertEqual(resp['msg'], 'Resultado OK')

    def test_el_timeout_http_separa_conectar_de_leer(self):
        """Lección DL-7 de Getnet: conectar falla rápido; leer da tiempo a ITD."""
        _resp, llamadas = self._post(respuesta_http(200, {'ResponseCode': 0}))
        conectar, leer = llamadas[0][2]
        self.assertLessEqual(conectar, 5)
        self.assertGreaterEqual(leer, conectar)

    def test_el_system_id_no_sale_en_el_log(self):
        """Credenciales jamás en log: el payload se enmascara antes de loguearlo."""
        post, _ = post_secuencial(respuesta_http(200, {'ResponseCode': 0}))
        with patch.object(fiserv_utils.requests, 'post', post), \
                self.assertLogs(fiserv_utils._logger.name, level='INFO') as log:
            self.provider._fiserv_itd_post('/x', {'SystemId': SYSTEM_ID_FALSO, 'PosID': 'P1'}, 't')
        salida = '\n'.join(log.output)
        self.assertNotIn(SYSTEM_ID_FALSO, salida)
        self.assertIn('***76', salida)

    # ------------------------------------------------------------------
    # Estado a partir de la respuesta
    # ------------------------------------------------------------------
    def test_mapa_de_estados(self):
        Tx = self.env['payment.transaction']
        self.assertEqual(Tx._get_transaction_state_with_pos_response('0', {'PosResponseCode': '00'}), 'done')
        self.assertEqual(Tx._get_transaction_state_with_pos_response('0', {'PosResponseCode': '05'}), 'error')
        self.assertEqual(Tx._get_transaction_state_with_pos_response('999', {}), 'error')
        self.assertEqual(Tx._get_transaction_state_with_pos_response('11', {}), 'error')
        self.assertEqual(Tx._get_transaction_state_with_pos_response('10', {}), 'pending')
        self.assertEqual(Tx._get_transaction_state_with_pos_response(TRANSPORTE, {}), 'pending')

    # ------------------------------------------------------------------
    # Bucle de consultas
    # ------------------------------------------------------------------
    def test_loop_aprobada_tras_estados_intermedios(self):
        driver = _DriverFalso([{'ResponseCode': '10'}, {'ResponseCode': '12'}, APROBADA])
        result = self._run_loop(driver, [0, 1, 2, 3])
        self.assertEqual(result['ResponseCode'], '0')
        self.assertFalse(driver.confirmados, 'sin NeedToReadCard no se confirma')

    def test_loop_confirma_una_sola_vez_tras_leer_tarjeta(self):
        con_tarjeta = {'ResponseCode': '12', 'Acquirer': '5', 'Issuer': '2', 'CardNumber': '4507'}
        driver = _DriverFalso([con_tarjeta, con_tarjeta, APROBADA])
        original = {'PosID': 'P0001', 'SystemId': SYSTEM_ID_FALSO, 'Branch': '', 'ClientAppId': '1',
                    'UserId': '2', 'Amount': '10000', 'NeedToReadCard': True}
        result = self._run_loop(driver, [0, 1, 2, 3], original=original)
        self.assertEqual(result['ResponseCode'], '0')
        self.assertEqual(len(driver.confirmados), 1)
        self.assertEqual(driver.confirmados[0]['TransactionId'], '4455')

    def test_loop_un_fallo_de_transporte_no_corta(self):
        """
        🔴 REGRESIÓN de 17.0: un solo 502 durante la espera cortaba el bucle
        con 999 y la transacción quedaba en `error` definitivo, aunque el
        pinpad aprobara un segundo después.
        """
        caida = {'ResponseCode': TRANSPORTE, 'msg': 'HTTP 502'}
        driver = _DriverFalso([caida, caida, APROBADA])
        result = self._run_loop(driver, [0, 1, 2, 3])
        self.assertEqual(result['ResponseCode'], '0')

    def test_loop_transporte_en_el_confirm_no_corta(self):
        """El confirm pudo haber llegado: se sigue consultando y ITD dirá."""
        con_tarjeta = {'ResponseCode': '12', 'Acquirer': '5', 'Issuer': '2'}
        driver = _DriverFalso([con_tarjeta, APROBADA], confirm={'ResponseCode': TRANSPORTE})
        original = {'PosID': 'P0001', 'SystemId': 'X', 'Branch': '', 'ClientAppId': '1',
                    'UserId': '2', 'NeedToReadCard': True}
        result = self._run_loop(driver, [0, 1, 2], original=original)
        self.assertEqual(result['ResponseCode'], '0')
        self.assertEqual(len(driver.confirmados), 1)

    def test_loop_confirm_rechazado_corta(self):
        con_tarjeta = {'ResponseCode': '12', 'Acquirer': '5', 'Issuer': '2'}
        driver = _DriverFalso([con_tarjeta, APROBADA], confirm={'ResponseCode': '-100'})
        original = {'PosID': 'P0001', 'SystemId': 'X', 'Branch': '', 'ClientAppId': '1',
                    'UserId': '2', 'NeedToReadCard': True}
        result = self._run_loop(driver, [0, 1], original=original)
        self.assertEqual(result['ResponseCode'], '-100')

    def test_loop_tope_sin_respuesta_queda_como_transporte(self):
        """Agotado el tope sin respuesta final: «no sé», nunca error."""
        driver = _DriverFalso([{'ResponseCode': TRANSPORTE}])
        result = self._run_loop(driver, [0, 10, pt_mod.FISERV_POLL_HARD_MAX + 1])
        self.assertEqual(result['ResponseCode'], TRANSPORTE)
        self.assertTrue(result.get('fiserv_timeout'))

    def test_loop_tope_con_pinpad_en_curso_tambien_queda_pendiente(self):
        driver = _DriverFalso([{'ResponseCode': '10', 'RemainingExpirationTime': '30'}])
        result = self._run_loop(driver, [0, pt_mod.FISERV_POLL_HARD_MAX + 1])
        self.assertEqual(result['ResponseCode'], TRANSPORTE)

    def test_loop_vencimiento_informado_por_itd_revierte(self):
        driver = _DriverFalso([{'ResponseCode': '10', 'RemainingExpirationTime': '0'}])
        result = self._run_loop(driver, [0, 1])
        self.assertEqual(result['ResponseCode'], '11')
        self.assertTrue(result['reverse_processed'])
        self.assertEqual(len(driver.revertidos), 1)

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def test_persistir_aprobada(self):
        tx = self._create_tx()
        tx._set_pending()
        pedido = dict(self.query_base, Amount='10000')
        self.assertEqual(tx._fiserv_persist_query_result(dict(APROBADA), pos_data=pedido), 'done')
        self.assertEqual(tx.ticket_number, '000123')
        self.assertEqual(tx.batch_number, '7')
        self.assertEqual(tx.authorization_code, 'A1B2')
        self.assertEqual(tx.card_last_four, '1234')
        self.assertEqual(tx.amount, 100.0)
        self.assertTrue(tx.reference.startswith('FISERV-P0001-000123'))
        guardado = json.loads(tx.fiserv_complete_request)
        self.assertNotEqual(guardado['SystemId'], SYSTEM_ID_FALSO,
                            'el request guardado lo lee cualquier contador')

    def test_persistir_rechazo_del_terminal(self):
        tx = self._create_tx()
        tx._set_pending()
        tx._fiserv_persist_query_result(dict(APROBADA, PosResponseCode='51'))
        self.assertEqual(tx.state, 'error')
        self.assertIn('SALDO INSUFICIENTE', tx.state_message)

    def test_persistir_transporte_queda_pendiente_y_para_verificar(self):
        tx = self._create_tx()
        tx._fiserv_persist_query_result({'ResponseCode': TRANSPORTE, 'msg': 'HTTP 504'})
        self.assertEqual(tx.state, 'pending')
        self.assertTrue(tx.fiserv_requiere_conciliacion)
        # Otra vuelta sin respuesta: sigue pendiente, con el mensaje nuevo.
        tx._fiserv_persist_query_result({'ResponseCode': TRANSPORTE, 'msg': 'timeout'})
        self.assertEqual(tx.state, 'pending')
        self.assertEqual(tx.state_message, 'timeout')

    def test_persistir_una_resolucion_posterior_limpia_la_marca(self):
        tx = self._create_tx()
        tx._fiserv_persist_query_result({'ResponseCode': TRANSPORTE, 'msg': 'x'})
        tx._fiserv_persist_query_result(dict(APROBADA))
        self.assertEqual(tx.state, 'done')
        self.assertFalse(tx.fiserv_requiere_conciliacion)

    def test_persistir_devolucion_guarda_monto_negativo(self):
        tx = self._create_tx(amount=-100.0)
        tx._set_pending()
        tx._fiserv_persist_query_result(dict(APROBADA))
        self.assertEqual(tx.amount, -100.0)

    def test_la_marca_del_emisor_sale_de_las_configuradas(self):
        tx = self._create_tx()
        tx._fiserv_persist_query_result(dict(APROBADA, Issuer='2'))
        self.assertEqual(tx.issuer_name, 'American Express')

    def test_no_autocrea_account_payment(self):
        """
        El post-procesamiento de account_payment crea y postea un pago por
        cada transacción done sin payment_id. Para Fiserv duplicaría el cobro.
        """
        tx = self._create_tx()
        tx._fiserv_persist_query_result(dict(APROBADA))
        antes = self.env['account.payment'].search_count([])
        tx._post_process()
        self.assertEqual(self.env['account.payment'].search_count([]), antes)
        self.assertFalse(tx.payment_id)

    def test_el_voucher_se_imprime_sin_el_modulo_pos(self):
        """
        El voucher leía `tx.pos_order_id`, que sin el módulo POS no existe:
        imprimir desde el flujo contable reventaba.
        """
        tx = self._create_tx()
        tx._fiserv_persist_query_result(dict(APROBADA))
        html, _tipo = self.env['ir.actions.report']._render_qweb_html(
            'odoo_pos_fiserv_core.action_report_payment_transaction_fiserv_voucher', tx.ids)
        self.assertIn(b'000123', html)

    # ------------------------------------------------------------------
    # Void / refund
    # ------------------------------------------------------------------
    def test_fallback_void_a_refund_solo_para_void_puro(self):
        f = fiserv_utils.fiserv_void_response_needs_refund_fallback
        void = {'TicketNumber': '123'}
        self.assertTrue(f(void, {'PosResponseCode': '25'}))
        self.assertTrue(f(void, {'posResponseCode': '21'}))
        self.assertFalse(f(void, {'PosResponseCode': '00'}))
        self.assertFalse(f({'TicketNumber': '123', 'Amount': '100'}, {'PosResponseCode': '25'}))
        self.assertFalse(f({'Amount': '100'}, {'PosResponseCode': '25'}))

    def _batch(self, respuesta):
        original = self._create_tx(ticket_number='000123', batch_number='7')
        with patch.object(type(self.provider), '_fiserv_itd_batch_query',
                          lambda prov, data: respuesta):
            return self.provider._fiserv_check_original_in_current_batch('P0001', original)

    def test_chequeo_de_lote(self):
        self.assertTrue(self._batch({'ResponseCode': '0', 'Transactions': [{'Ticket': '123'}]}))
        self.assertIs(self._batch({'ResponseCode': '0', 'Transactions': [{'Ticket': '999'}]}), False)
        self.assertIs(self._batch({'ResponseCode': '0', 'Transactions': []}), False)
        self.assertIsNone(self._batch({'ResponseCode': TRANSPORTE}))

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------
    def test_la_capa_itd_no_es_alcanzable_por_rpc(self):
        """
        Odoo no expone por RPC los métodos con guion bajo. En 17.0 la capa
        HTTP y la persistencia eran públicas: cualquiera con acceso al modelo
        podía disparar un POST a ITD o escribir un resultado «aprobado».
        """
        Provider = type(self.env['payment.provider'])
        Tx = type(self.env['payment.transaction'])
        for viejo in ('processFinancialPurchaseQuery', 'processFinancialReverse',
                      'processCurrentTransactionsBatchQuery', 'get_formatted_timestamp',
                      'fiserv_process_financial_purchase_contable',
                      'fiserv_process_financial_purchase_void_contable'):
            self.assertFalse(hasattr(Provider, viejo), viejo)
        for viejo in ('update_fiserv_transaction', 'create_fiserv_transaction',
                      'create_fiserv_transaction_with_complete_data',
                      'fiserv_run_purchase_query_loop', 'fiserv_persist_after_query_generic',
                      'get_fiserv_display_message'):
            self.assertFalse(hasattr(Tx, viejo), viejo)
        publicos = [n for n in dir(Tx) if n.startswith('fiserv') and callable(getattr(Tx, n))]
        self.assertEqual(publicos, ['fiserv_action_conciliada'])

    def test_verificada_exige_grupo_contabilidad(self):
        tx = self._create_tx()
        tx._fiserv_marcar_conciliacion('prueba de permisos')
        with self.assertRaises(AccessError):
            tx.with_user(self._usuario('base.group_user')).fiserv_action_conciliada()
        self.assertTrue(tx.fiserv_requiere_conciliacion)
        tx.with_user(self._usuario('base.group_user', 'account.group_account_user')).fiserv_action_conciliada()
        tx.invalidate_recordset()
        self.assertFalse(tx.fiserv_requiere_conciliacion)
        self.assertEqual(tx.state, 'cancel', 'verificada sin cobro: la transacción se cancela')

    def test_el_contador_lee_transacciones(self):
        contador = self._usuario('base.group_user', 'account.group_account_user')
        tx = self._create_tx()
        self.assertEqual(tx.with_user(contador).read(['fiserv_transaction_id'])[0]['fiserv_transaction_id'], '4455')

    def test_el_contador_llega_al_menu_de_transacciones(self):
        """
        En 17.0 el menú colgaba de Configuración, que es sólo del
        administrador contable: el contador no llegaba a la lista que tiene
        que revisar. Se mira la cadena entera de menús padre.
        """
        contador = self._usuario('base.group_user', 'account.group_account_user')
        menu = self.env.ref('odoo_pos_fiserv_core.menu_payment_transaction_fiserv')
        visibles = self.env['ir.ui.menu'].with_user(contador)._visible_menu_ids()
        while menu:
            self.assertIn(menu.id, visibles, menu.complete_name)
            menu = menu.parent_id

    def test_el_system_id_es_solo_de_ajustes(self):
        self.assertEqual(self.env['payment.provider']._fields['fiserv_system_id'].groups,
                         'base.group_system')

    def test_un_usuario_interno_no_edita_terminales(self):
        interno = self._usuario('base.group_user')
        with self.assertRaises(AccessError):
            self.terminal.with_user(interno).write({'pos_id': 'OTRO'})

    # ------------------------------------------------------------------
    # Commits y runtime
    # ------------------------------------------------------------------
    def test_safe_commit_no_commitea_en_tests(self):
        with patch.object(type(self.env.cr), 'commit', side_effect=AssertionError('commit real')):
            fiserv_utils.fiserv_safe_commit(self.env)

    def test_aviso_runtime_test_enable_con_proveedor_activo(self):
        Provider = self.env['payment.provider']
        with patch.object(pp_mod, 'config', {'test_enable': True, 'stop_after_init': False}):
            with self.assertLogs(pp_mod._logger.name, level='WARNING') as capturado:
                aviso = Provider._fiserv_avisar_runtime_invalido()
        self.assertTrue(aviso)
        self.assertTrue(any('NO operar Fiserv' in linea for linea in capturado.output))

    def test_no_avisa_durante_una_corrida_de_tests(self):
        Provider = self.env['payment.provider']
        with patch.object(pp_mod, 'config', {'test_enable': True, 'stop_after_init': True}):
            self.assertFalse(Provider._fiserv_avisar_runtime_invalido())

    def test_no_avisa_sin_proveedor_fiserv_activo(self):
        """Se apagan TODOS: un test que depende de la base vacía prueba la base."""
        Provider = self.env['payment.provider']
        Provider.sudo().search([('code', '=', 'fiserv')]).state = 'disabled'
        with patch.object(pp_mod, 'config', {'test_enable': True, 'stop_after_init': False}):
            self.assertFalse(Provider._fiserv_avisar_runtime_invalido())
