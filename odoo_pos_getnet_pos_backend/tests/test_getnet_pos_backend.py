# -*- coding: utf-8 -*-
"""
La terminal Getnet contra el contrato de `pos_backend`.

Lo que se prueba acá es el CONTRATO, no la terminal: el SOAP va mockeado y el
reloj es el del harness compartido del núcleo —nunca sleeps de verdad—. Lo que
no se puede probar sin hardware está escrito en el §6 del contrato y no se
simula.

Los hooks se ejercitan por sus `_inner`, que reciben el `env`: el wrapper que
abre el cursor propio no puede correr dentro de una TransactionCase, porque un
cursor nuevo no ve los datos sin commitear del test. Que el wrapper exista y
que NADIE commitee a mano se prueba aparte.
"""

import uuid
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils
from odoo.addons.odoo_pos_getnet_core.models import (
    payment_transaction as pt_mod,
)
from odoo.addons.odoo_pos_getnet_core.tests.common import _RelojDeLaboratorio
from odoo.addons.odoo_pos_getnet_pos_backend.models import (
    pos_backend_terminal_getnet as pb_mod,
)
from odoo.addons.pos_backend.models.pos_backend_terminal import (
    RESULT_APPROVED,
    RESULT_REJECTED,
    RESULT_UNKNOWN,
)

POSTEO_OK = {'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-PB-1',
             'Resp_TokenSegundosReConsultar': '1'}
POSTEO_RECHAZADO = {'Resp_CodigoRespuesta': '2',
                    'Resp_MensajeError': 'CAMPO REQUERIDO / VERIFIQUE'}
EN_PROCESO = {'Resp_CodigoRespuesta': '0',
              'Resp_EstadoAvance': 'ESTADOAVANCE_ENPROCESO',
              'Resp_TransaccionFinalizada': 'false',
              'Resp_TokenSegundosReConsultar': '1'}
APROBADA = {'Resp_CodigoRespuesta': '0',
            'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE',
            'Resp_TransaccionFinalizada': 'true', 'Aprobada': 'true',
            'TransaccionId': '77', 'Ticket': '5150', 'Lote': '3',
            'NroAutorizacion': 'A9', 'MsgRespuesta': 'APROBADA'}
DENEGADA = {'Resp_CodigoRespuesta': '0',
            'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_ERROR',
            'Resp_TransaccionFinalizada': 'true', 'Aprobada': 'false',
            'CodRespAdq': '51', 'Ticket': '0', 'MsgRespuesta': 'DENEGADA'}
CANCEL_OK = {'Resp_CodigoRespuesta': '0'}


@tagged('post_install', '-at_install')
class TestGetnetPosBackend(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Getnet POS Backend Test',
            'code': 'getnet',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE',
            'getnet_emp_hash': 'FAKEHASH00000000FAKEHASH00000000',
            # Un payment.provider NACE 'disabled', y `terminal_is_available`
            # lo verifica: sin esto el medio sale apagado y el fixture mentiría.
            'state': 'test',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Pinpad Caja PB',
            'term_cod': 'T00009',
            'payment_provider_id': cls.provider.id,
        })
        cls.local = cls.env['pos_backend.local'].create(
            {'name': 'Local Getnet PB'})
        cls.box = cls.env['pos_backend.box'].create(
            {'name': 'Caja Getnet PB', 'local_id': cls.local.id})
        journal = cls.env['account.journal'].create({
            'name': 'Tarjetas a cobrar PB',
            'type': 'bank',
            'code': 'TACPB',
            'company_id': cls.box.company_id.id,
        })
        cls.metodo = cls.env['pos_backend.box.payment.method'].create({
            'box_id': cls.box.id,
            'name': 'Getnet PB',
            'payment_type': 'integrado',
            'journal_id': journal.id,
            'terminal_provider': 'getnet',
            'getnet_terminal_id': cls.terminal.id,
        })
        cls.uyu = cls.env.ref('base.UYU')

    # ------------------------------------------------------------------
    def _impl(self):
        return self.env['pos_backend.terminal.getnet']

    def _soap(self, guion):
        """Mockea el SOAP con un guion, y deja ver qué se llamó."""
        llamadas = []

        def fake(prov, metodo, params):
            llamadas.append((metodo, params))
            return (dict(guion.pop(0)), '<req/>', '<resp/>')

        return llamadas, patch.object(
            type(self.provider), '_getnet_soap_transaccion', fake)

    def _sin_commits(self):
        """Ningún commit de verdad dentro del test: rompe el savepoint."""
        llamadas = []
        return llamadas, patch.object(
            getnet_utils, 'getnet_safe_commit',
            lambda env: llamadas.append(env))

    def _reloj(self, secuencia):
        return patch.object(pt_mod, 'time', _RelojDeLaboratorio(secuencia))

    # ==================================================================
    # §3.1 · Anunciarse
    # ==================================================================
    def test_el_proveedor_se_anuncia_en_la_lista(self):
        opciones = dict(
            self.env['pos_backend.box.payment.method']
            ._fields['terminal_provider'].selection)
        self.assertIn('getnet', opciones)

    def test_el_pos_resuelve_la_implementacion(self):
        """El POS no conoce el nombre del módulo: pregunta por el proveedor."""
        self.assertEqual(
            self.metodo._get_terminal(),
            self.env['pos_backend.terminal.getnet'])

    def test_getnet_sin_pinpad_no_se_puede_guardar(self):
        """Proveedor elegido y ninguna terminal es el mismo agujero un nivel
        más abajo que un medio integrado sin proveedor."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.metodo.getnet_terminal_id = False

    # ==================================================================
    # 1 · ¿Estás disponible?
    # ==================================================================
    def test_disponible_sin_hablarle_al_pinpad(self):
        llamadas, parche = self._soap([])
        with parche:
            respuesta = self._impl().terminal_is_available(self.metodo)
        self.assertTrue(respuesta['available'])
        self.assertFalse(respuesta['reason'])
        self.assertEqual(llamadas, [], 'se le habló al pinpad al abrir el cobro')

    def test_proveedor_deshabilitado_apaga_el_medio(self):
        self.provider.state = 'disabled'
        respuesta = self._impl().terminal_is_available(self.metodo)
        self.assertFalse(respuesta['available'])
        self.assertIn('deshabilitado', respuesta['reason'])

    def test_terminal_tomada_por_otro_flujo_apaga_el_medio(self):
        """El lock es entre flujos: el mismo pinpad no atiende dos cobros."""
        self.terminal.getnet_claim('account_payment', ref='OTRO')
        respuesta = self._impl().terminal_is_available(self.metodo)
        self.assertFalse(respuesta['available'])
        self.assertIn('ocupada', respuesta['reason'])

    def test_medio_sin_terminal_da_un_motivo_accionable(self):
        otro = self.env['pos_backend.box.payment.method'].create({
            'box_id': self.box.id,
            'name': 'Integrado sin pinpad',
            'payment_type': 'integrado',
            'journal_id': self.metodo.journal_id.id,
        })
        respuesta = self._impl().terminal_is_available(otro)
        self.assertFalse(respuesta['available'])
        self.assertIn('terminal Getnet', respuesta['reason'])

    # ==================================================================
    # 2 · Autorizar
    # ==================================================================
    def test_el_payload_no_lleva_numero_de_factura(self):
        """
        En el POS el CFE se emite al FINALIZAR la venta, o sea después de
        cobrar: cuando se pide la autorización no hay número que mandar. Va 0,
        que es el valor que el concentrador acepta (omitirlo da rc=2).
        """
        vals = self._impl()._getnet_payload_venta(
            self.provider, self.terminal, 3400.0, self.uyu)
        self.assertEqual(vals['FacturaNro'], 0)
        self.assertEqual(vals['Operacion'], 'VTA')
        self.assertEqual(vals['Monto'], 340000)
        self.assertEqual(vals['TermCod'], 'T00009')
        self.assertEqual(vals['MonedaISO'], '0858')
        self.assertNotIn('DecretoLeyId', vals)
        for clave in ('FacturaMonto', 'FacturaMontoGravado',
                      'FacturaMontoIVA', 'FacturaConsumidorFinal'):
            self.assertNotIn(clave, vals)

    def test_aprobada_dentro_de_la_ventana(self):
        """El caso normal: la tarjeta ya está en la mano y contesta rápido."""
        referencia = 'PB-%s' % uuid.uuid4().hex[:8]
        guion = [POSTEO_OK, APROBADA]
        llamadas, parche_soap = self._soap(guion)
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit, self._reloj([0, 1, 2]):
            respuesta = self._impl()._getnet_authorize_inner(
                self.env, self.metodo.id, 3400.0, self.uyu, referencia)
        self.assertEqual(respuesta['result'], RESULT_APPROVED)
        self.assertEqual(respuesta['transaction_id'], '5150')
        tx = self._impl()._getnet_tx_de_referencia(self.env, referencia)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.getnet_transaction_origin, 'pos_backend')
        # La terminal queda libre: el cobro terminó.
        self.assertFalse(self.terminal.lock_origin)

    def test_si_la_ventana_expira_se_contesta_no_se(self):
        """
        Invariante 4: el llamador no distingue. La ventana vence y se informa
        exactamente lo mismo que informaría un módulo sin ventana —«no sé»—,
        con la transacción viva y su token para poder resolverla.
        """
        referencia = 'PB-%s' % uuid.uuid4().hex[:8]
        guion = [POSTEO_OK] + [EN_PROCESO for _ in range(8)]
        llamadas, parche_soap = self._soap(guion)
        _commits, parche_commit = self._sin_commits()
        # El reloj salta por encima de la ventana después de la 1ra consulta.
        with parche_soap, parche_commit, self._reloj([0, 1, 100, 200]):
            respuesta = self._impl()._getnet_authorize_inner(
                self.env, self.metodo.id, 500.0, self.uyu, referencia)
        self.assertEqual(respuesta['result'], RESULT_UNKNOWN)
        tx = self._impl()._getnet_tx_de_referencia(self.env, referencia)
        self.assertEqual(tx.state, 'pending')
        self.assertTrue(tx.getnet_token)
        # NUNCA se cancela dentro de la ventana: el cliente puede estar
        # aprobando en el pinpad justo en ese momento.
        self.assertNotIn('CancelarTransaccion', [c[0] for c in llamadas])
        self.assertFalse(self.terminal.lock_origin)

    def test_lo_que_la_ventana_no_resolvio_lo_resuelve_la_consulta(self):
        """Invariante 5, la otra rama: expiración resuelta después."""
        referencia = 'PB-%s' % uuid.uuid4().hex[:8]
        guion = [POSTEO_OK] + [EN_PROCESO for _ in range(4)]
        _ll, parche_soap = self._soap(guion)
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit, self._reloj([0, 1, 100, 200]):
            self._impl()._getnet_authorize_inner(
                self.env, self.metodo.id, 500.0, self.uyu, referencia)

        guion2 = [APROBADA]
        _ll2, parche_soap2 = self._soap(guion2)
        with parche_soap2, parche_commit, self._reloj([0, 1]):
            respuesta = self._impl()._getnet_query_inner(
                self.env, self.metodo.id, referencia)
        self.assertEqual(respuesta['result'], RESULT_APPROVED)
        tx = self._impl()._getnet_tx_de_referencia(self.env, referencia)
        self.assertEqual(tx.state, 'done')

    def test_un_posteo_rechazado_es_un_rechazo_y_libera_la_terminal(self):
        """El concentrador no aceptó la operación: no hay nada en el pinpad."""
        referencia = 'PB-%s' % uuid.uuid4().hex[:8]
        _ll, parche_soap = self._soap([POSTEO_RECHAZADO])
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit:
            respuesta = self._impl()._getnet_authorize_inner(
                self.env, self.metodo.id, 100.0, self.uyu, referencia)
        self.assertEqual(respuesta['result'], RESULT_REJECTED)
        self.assertIn('CAMPO REQUERIDO', respuesta['message'])
        self.assertFalse(self.terminal.lock_origin)

    def test_un_fallo_de_transporte_NO_es_un_rechazo(self):
        """
        🔴 Lo encontró un dry-run con el concentrador caído de verdad. El rc
        999 lo pone nuestro cliente SOAP cuando no hubo respuesta usable —un
        timeout, un 502—, y el pedido PUDO haber llegado igual. Contestar
        «rechazada» ahí descarta una transacción que quizá existe, que es el
        error del §3.3 que cuesta plata.
        """
        referencia = 'PB-%s' % uuid.uuid4().hex[:8]
        transporte = {
            'Resp_CodigoRespuesta': getnet_utils.GETNET_RC_TRANSPORTE,
            'Resp_MensajeError': 'HTTP 504 del concentrador',
        }
        _ll, parche_soap = self._soap([transporte])
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit:
            respuesta = self._impl()._getnet_authorize_inner(
                self.env, self.metodo.id, 100.0, self.uyu, referencia)
        self.assertEqual(respuesta['result'], RESULT_UNKNOWN)
        self.assertIn('504', respuesta['message'])
        tx = self._impl()._getnet_tx_de_referencia(self.env, referencia)
        self.assertEqual(tx.state, 'pending')
        self.assertFalse(self.terminal.lock_origin)

    def test_una_tarjeta_denegada_es_un_rechazo(self):
        referencia = 'PB-%s' % uuid.uuid4().hex[:8]
        _ll, parche_soap = self._soap([POSTEO_OK, DENEGADA])
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit, self._reloj([0, 1, 2]):
            respuesta = self._impl()._getnet_authorize_inner(
                self.env, self.metodo.id, 100.0, self.uyu, referencia)
        self.assertEqual(respuesta['result'], RESULT_REJECTED)

    # ==================================================================
    # 3 · Consultar
    # ==================================================================
    def test_una_referencia_desconocida_no_afirma_que_no_paso_nada(self):
        respuesta = self._impl()._getnet_query_inner(
            self.env, self.metodo.id, 'NO-EXISTE-NUNCA')
        self.assertEqual(respuesta['result'], RESULT_UNKNOWN)

    def test_las_tres_respuestas_salen_del_estado_de_la_transaccion(self):
        """No son dos. `error` es la terminal diciendo NO; `pending` es no
        saber, y puede haber plata cobrada."""
        esperado = {
            'done': RESULT_APPROVED,
            'error': RESULT_REJECTED,
            'cancel': RESULT_REJECTED,
            'pending': RESULT_UNKNOWN,
            'draft': RESULT_UNKNOWN,
        }
        for estado, resultado in esperado.items():
            self.assertEqual(
                pb_mod.GETNET_ESTADO_A_RESULTADO.get(estado, RESULT_UNKNOWN),
                resultado, estado)

    # ==================================================================
    # 4 y 5 · Reversar y devolver
    # ==================================================================
    def _tx_hecha(self, estado='done', ticket='5150'):
        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': self.env.ref(
                'odoo_pos_getnet_core.payment_method_getnet').id,
            'reference': 'GETNET-PB-%s' % uuid.uuid4().hex[:10],
            'amount': 100.0,
            'currency_id': self.uyu.id,
            'partner_id': self.env.company.partner_id.id,
            'getnet_token': 'TOK-%s' % uuid.uuid4().hex[:6],
            'getnet_ticket': ticket,
            'getnet_terminal_id': self.terminal.id,
            'getnet_transaction_origin': 'pos_backend',
        })
        if estado == 'done':
            tx._set_done()
        elif estado == 'pending':
            tx._set_pending()
        return tx

    def test_reversar_una_pendiente_la_cancela(self):
        tx = self._tx_hecha(estado='pending', ticket='0')
        llamadas, parche_soap = self._soap([CANCEL_OK])
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit:
            respuesta = self._impl()._getnet_reverse_inner(
                self.env, self.metodo.id, '0')
        self.assertTrue(respuesta['ok'])
        self.assertEqual(llamadas[0][0], 'CancelarTransaccion')

    def test_reversar_una_aprobada_manda_una_devolucion(self):
        """
        En TransAct una transacción aprobada no se cancela: se devuelve. El
        hook hace lo que corresponde al estado real, no lo que dice su nombre.
        """
        tx = self._tx_hecha(estado='done', ticket='5151')
        guion = [POSTEO_OK, APROBADA]
        llamadas, parche_soap = self._soap(guion)
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit, self._reloj([0, 1, 2]):
            respuesta = self._impl()._getnet_reverse_inner(
                self.env, self.metodo.id, '5151')
        self.assertTrue(respuesta['ok'])
        posteos = [c for c in llamadas if c[0] == 'PostearTransaccion']
        self.assertTrue(posteos)
        self.assertEqual(
            posteos[0][1]['Transaccion']['Operacion'], 'DEV')
        self.assertEqual(
            posteos[0][1]['Transaccion']['TicketOriginal'], 5151)

    def test_una_devolucion_sin_confirmar_no_se_da_por_buena(self):
        """
        El «no sé» de SALIDA es peor que el de entrada: reintentar a ciegas
        puede regalar el importe. Se informa que NO salió.
        """
        self._tx_hecha(estado='done', ticket='5152')
        guion = [POSTEO_OK] + [EN_PROCESO for _ in range(20)]
        _ll, parche_soap = self._soap(guion)
        _commits, parche_commit = self._sin_commits()
        with parche_soap, parche_commit, self._reloj(
                [0] + [n * 100 for n in range(1, 30)]):
            respuesta = self._impl()._getnet_refund_inner(
                self.env, self.metodo.id, '5152', 100.0)
        self.assertFalse(respuesta['ok'])

    def test_la_operacion_6_no_se_implementa(self):
        """
        Getnet no sabe si el adquirente liquidó, y el «no sé» del contrato
        elige DEVOLUCIÓN, que es el camino correcto por la asimetría de costo
        del §7.3. El default del contrato es lo que tiene que correr.
        """
        self.assertEqual(
            self._impl().terminal_is_settled(self.metodo, '5150'),
            {'settled': None})

    # ==================================================================
    # 7 · Cerrar el lote
    # ==================================================================
    def test_con_transacciones_en_vuelo_no_se_intenta_el_cierre(self):
        """
        El cierre de TransAct REVERSA las pendientes de confirmación, así que
        intentarlo sería resolver por la fuerza algo que todavía se puede
        resolver bien. Se informa y decide el POS.
        """
        self._tx_hecha(estado='pending')
        # La sesión se crea a mano y no con _open(): abrirla exige que el
        # usuario esté habilitado en la caja, y el hook no lee nada de la
        # sesión —la recibe porque el contrato se la pasa—. Montar el permiso
        # entero sería fixture que no prueba nada de este módulo.
        sesion = self.env['pos_backend.session'].sudo().create({
            'box_id': self.box.id,
            'name': 'SES-GETNET-PB-%s' % uuid.uuid4().hex[:6],
        })
        llamadas, parche_soap = self._soap([])
        with parche_soap:
            respuesta = self._impl()._getnet_close_batch_inner(
                self.env, self.metodo.id, sesion.id)
        self.assertFalse(respuesta['ok'])
        self.assertEqual(respuesta['in_flight'], 1)
        self.assertEqual(llamadas, [], 'se intentó cerrar el lote igual')

    def test_el_medio_sin_pinpad_informa_el_motivo_y_no_explota(self):
        otro = self.env['pos_backend.box.payment.method'].create({
            'box_id': self.box.id,
            'name': 'Integrado sin pinpad cierre',
            'payment_type': 'integrado',
            'journal_id': self.metodo.journal_id.id,
        })
        # La sesión se crea a mano y no con _open(): abrirla exige que el
        # usuario esté habilitado en la caja, y el hook no lee nada de la
        # sesión —la recibe porque el contrato se la pasa—. Montar el permiso
        # entero sería fixture que no prueba nada de este módulo.
        sesion = self.env['pos_backend.session'].sudo().create({
            'box_id': self.box.id,
            'name': 'SES-GETNET-PB-%s' % uuid.uuid4().hex[:6],
        })
        respuesta = self._impl()._getnet_close_batch_inner(
            self.env, otro.id, sesion.id)
        self.assertFalse(respuesta['ok'])
        self.assertEqual(respuesta['in_flight'], 0)
        self.assertIn('terminal Getnet', respuesta['message'])

    # ==================================================================
    # La regla del módulo: nunca commitear la transacción del llamador
    # ==================================================================
    def test_ningun_commit_crudo_en_el_modulo(self):
        """
        Todo commit pasa por getnet_safe_commit. Un `cr.commit()` a mano acá
        publicaría el pedido a medio construir del POS, y en un test rompe el
        savepoint de la TransactionCase.
        """
        import inspect

        fuente = inspect.getsource(pb_mod)
        # Se descuentan las menciones en comentarios, que sí hablan del tema.
        codigo = '\n'.join(
            linea for linea in fuente.splitlines()
            if not linea.strip().startswith('#'))
        self.assertNotIn('cr.commit()', codigo)

    def test_el_cursor_propio_se_abre_con_la_api_de_19(self):
        """
        REGRESIÓN: en 19.0 `odoo.registry` YA NO EXISTE —el core usa
        `odoo.modules.registry.Registry`— y el wrapper lo usaba. Lo encontró
        un dry-run contra la base real, no la suite: todos los tests sustituyen
        el wrapper justamente para poder ver los datos del test, así que su
        cuerpo no corría nunca.

        Acá corre de verdad, con el Registry sustituido para que reuse el
        cursor del test. Se prueba la plomería —abrir cursor y armar el
        Environment—, que es lo que se rompió.
        """
        from contextlib import contextmanager

        cursor = self.env.cr

        class _RegistroFalso:
            @contextmanager
            def cursor(self):
                # Se cede el cursor del test y NO se lo cierra.
                yield cursor

        visto = {}

        def trabajo(env):
            # Un recordset vacío es FALSY: se guarda el _name, que es lo que
            # prueba que el Environment se armó y resuelve modelos.
            visto['modelo'] = env['pos_backend.box.payment.method']._name
            visto['uid'] = env.uid
            return 'listo'

        with patch('odoo.modules.registry.Registry',
                   lambda dbname: _RegistroFalso()):
            resultado = self._impl()._getnet_en_cursor_propio(trabajo)

        self.assertEqual(resultado, 'listo')
        self.assertEqual(visto['uid'], self.env.uid)
        self.assertEqual(visto['modelo'], 'pos_backend.box.payment.method')

    def test_los_seis_hooks_abren_cursor_propio(self):
        """
        El wrapper de cursor no se puede ejercitar dentro de una
        TransactionCase, pero su ausencia sí se puede cazar: cada hook del
        contrato tiene que delegar en `_getnet_en_cursor_propio`.
        """
        import inspect

        for hook in ('terminal_authorize', 'terminal_query', 'terminal_reverse',
                     'terminal_refund', 'terminal_close_batch'):
            fuente = inspect.getsource(getattr(pb_mod.PosBackendTerminalGetnet,
                                               hook))
            self.assertIn('_getnet_en_cursor_propio', fuente, hook)
