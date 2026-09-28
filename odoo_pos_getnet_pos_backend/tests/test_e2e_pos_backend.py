# -*- coding: utf-8 -*-
"""
Punta a punta: el POS Backend cobrando de verdad con la terminal Getnet.

A diferencia de la otra suite —que ejercita los hooks uno por uno— acá se entra
por la puerta que usa la pantalla de cobro (`pos_backend.app.add_payment_line`)
y se mira la LÍNEA DE PAGO que queda. Es la única forma de saber que el
contrato se cumple donde importa: en el estado de integración de la línea, que
es lo que después decide si la venta se puede finalizar.

**EL PAR DE EVIDENCIA.** Cada escenario se corre DOS VECES sobre la misma
pantalla: una con el módulo de ejemplo del Sprint 12 y otra con Getnet, y se
exige que el POS quede EXACTAMENTE IGUAL. El ejemplo es la referencia de lo que
el contrato promete; si Getnet se aparta, se aparta del contrato y no de una
opinión nuestra. Un test que sólo mira a Getnet no puede distinguir «cumple el
contrato» de «hace lo que nosotros creímos».

El wrapper de cursor propio se sustituye por el `env` del test: un cursor nuevo
no ve los datos sin commitear. Que los hooks lo abran de verdad lo fija un test
aparte, en la otra suite.
"""

import uuid
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_getnet_core.models import (
    payment_transaction as pt_mod,
)
from odoo.addons.odoo_pos_getnet_core.tests.common import _RelojDeLaboratorio

POSTEO_OK = {'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-E2E',
             'Resp_TokenSegundosReConsultar': '1'}
EN_PROCESO = {'Resp_CodigoRespuesta': '0',
              'Resp_EstadoAvance': 'ESTADOAVANCE_ENPROCESO',
              'Resp_TransaccionFinalizada': 'false',
              'Resp_TokenSegundosReConsultar': '1'}
APROBADA = {'Resp_CodigoRespuesta': '0',
            'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE',
            'Resp_TransaccionFinalizada': 'true', 'Aprobada': 'true',
            'TransaccionId': '88', 'Ticket': '7001', 'Lote': '4',
            'NroAutorizacion': 'B7', 'MsgRespuesta': 'APROBADA'}
DENEGADA = {'Resp_CodigoRespuesta': '0',
            'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_ERROR',
            'Resp_TransaccionFinalizada': 'true', 'Aprobada': 'false',
            'CodRespAdq': '51', 'Ticket': '0', 'MsgRespuesta': 'SIN FONDOS'}


@tagged('post_install', '-at_install')
class TestE2EPosBackendGetnet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Getnet E2E',
            'code': 'getnet',
            'state': 'test',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE',
            'getnet_emp_hash': 'FAKEHASH00000000FAKEHASH00000000',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Pinpad E2E', 'term_cod': 'T00011',
            'payment_provider_id': cls.provider.id,
        })
        cls.local = cls.env['pos_backend.local'].create({'name': 'Local E2E'})
        cls.box = cls.env['pos_backend.box'].create(
            {'name': 'Caja E2E', 'local_id': cls.local.id})
        journal = cls.env['account.journal'].create({
            'name': 'Tarjetas E2E', 'type': 'bank', 'code': 'TACE2',
            'company_id': cls.box.company_id.id,
        })
        # Aislamiento fiscal: sin un diario de ventas propio la factura cae en
        # el real y la localización emite el CFE de verdad dentro del test.
        cls.env['account.journal'].sudo().create({
            'name': 'Ventas Aisladas E2E', 'type': 'sale', 'code': 'VAISE',
            'sequence': 1, 'company_id': cls.box.company_id.id,
            'l10n_latam_use_documents': False,
        })
        cls.metodo_getnet = cls.env['pos_backend.box.payment.method'].create({
            'box_id': cls.box.id, 'name': 'Getnet E2E',
            'payment_type': 'integrado', 'journal_id': journal.id,
            'available_for_collect': True,
            'terminal_provider': 'getnet',
            'getnet_terminal_id': cls.terminal.id,
        })
        cls.metodo_demo = cls.env['pos_backend.box.payment.method'].create({
            'box_id': cls.box.id, 'name': 'Demo E2E',
            'payment_type': 'integrado', 'journal_id': journal.id,
            'available_for_collect': True,
            'terminal_provider': 'demo',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente E2E'})
        cls.product = cls.env['product.product'].create({'name': 'Producto E2E'})
        # El pedido lo mueve un usuario CON rol, no sudo: `sudo()` deja
        # `env.user` como está y los controles de pos_backend miran el rol de
        # quien se identificó, no el superusuario.
        cls.manager = cls.env['res.users'].create({
            'name': 'Manager E2E',
            'login': 'manager_e2e_getnet',
            'email': 'manager_e2e_getnet@example.com',
            'group_ids': [(6, 0, [
                cls.env.ref('pos_backend.group_pos_manager').id])],
        })
        cls.app = cls.env['pos_backend.app'].with_user(cls.manager)
        # La base puede traer cobros REALES aprobados del POS Backend que el
        # cron de huérfanos consideraría suyos (en una base de staging, los
        # de una sesión de prueba). Se sacan del circuito dentro de la
        # transacción del test —se revierte—, igual que el núcleo neutraliza
        # los tokens en vuelo: los tests miran sólo lo que ellos arman.
        cls.env['payment.transaction'].sudo().search([
            ('getnet_transaction_origin', '=', 'pos_backend'),
            ('state', '=', 'done'),
            ('getnet_requiere_conciliacion', '=', False),
        ]).write({'getnet_requiere_conciliacion': True})

    # ------------------------------------------------------------------
    def setUp(self):
        super().setUp()
        # El cursor propio se sustituye por el del test (ver el docstring).
        impl = self.env['pos_backend.terminal.getnet']
        self.patch(type(impl), '_getnet_en_cursor_propio',
                   lambda modelo, trabajo: trabajo(self.env))

    def _sesion(self):
        sesion = self.env['pos_backend.session'].sudo().search(
            [('box_id', '=', self.box.id), ('state', '=', 'open')], limit=1)
        if not sesion:
            sesion = self.env['pos_backend.session'].sudo().create({
                'box_id': self.box.id,
                'name': 'SES-E2E-%s' % uuid.uuid4().hex[:6],
            })
        return sesion

    def _pedido_tomado(self, monto=1200.0):
        sesion = self._sesion()
        order = self.env['pos_backend.order'].with_user(self.manager).create({
            'partner_id': self.partner.id, 'local_id': self.local.id})
        self.env['pos_backend.order.line'].with_user(self.manager).create({
            'order_id': order.id, 'product_id': self.product.id,
            'quantity': 1.0, 'price_unit': monto})
        order.action_send_to_collect()
        # La toma va por `_workflow_write`, que es el único camino válido para
        # los campos protegidos del pedido. `action_take` exigiría además la
        # sesión abierta por este usuario y un empleado habilitado como cajero
        # en el local: montar ese permiso no prueba nada de este módulo, y el
        # modelo de permisos de pos_backend ya tiene su propia suite.
        order.sudo()._workflow_write({
            'state': 'tomado', 'session_id': sesion.id,
            'box_id': self.box.id})
        return order.with_user(self.manager)

    def _soap(self, guion):
        def fake(prov, metodo, params):
            return (dict(guion.pop(0)), '<req/>', '<resp/>')
        return patch.object(
            type(self.provider), '_getnet_soap_transaccion', fake)

    def _cobrar_getnet(self, order, guion, reloj, monto=1200.0):
        with self._soap(guion), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio(reloj)):
            self.app.add_payment_line(
                order.id, self.metodo_getnet.id, monto)
        return order.payment_line_ids.sorted('id')[-1]

    def _cobrar_demo(self, order, comportamiento, monto=1200.0):
        self.metodo_demo.demo_behaviour = comportamiento
        self.app.add_payment_line(order.id, self.metodo_demo.id, monto)
        return order.payment_line_ids.sorted('id')[-1]

    # ==================================================================
    # PAR 1 · aprobada
    # ==================================================================
    def test_par_aprobada_el_pos_queda_igual_con_demo_y_con_getnet(self):
        """El cobro aprobado deja la línea AUTORIZADA, venga de donde venga."""
        pedido_demo = self._pedido_tomado()
        linea_demo = self._cobrar_demo(pedido_demo, 'aprueba')

        pedido_getnet = self._pedido_tomado()
        linea_getnet = self._cobrar_getnet(
            pedido_getnet, [POSTEO_OK, APROBADA], [0, 1, 2])

        self.assertEqual(linea_demo.integration_state, 'autorizado')
        self.assertEqual(linea_getnet.integration_state,
                         linea_demo.integration_state)
        # Las dos dejan referencia e identificador de transacción.
        for linea in (linea_demo, linea_getnet):
            self.assertTrue(linea.transaction_reference)
            self.assertTrue(linea.transaction_id)
        self.assertEqual(linea_getnet.transaction_id, '7001')

    # ==================================================================
    # PAR 2 · rechazada
    # ==================================================================
    def test_par_rechazada_no_deja_linea_y_la_venta_sigue_viva(self):
        """
        Contrato §1.2: un rechazo NO crea línea y el pedido queda como estaba.
        Es de los puntos donde más módulos se equivocan, así que se compara
        contra el ejemplo y no contra lo que creemos.
        """
        from odoo.exceptions import UserError

        pedido_demo = self._pedido_tomado()
        antes_demo = len(pedido_demo.payment_line_ids)
        self.metodo_demo.demo_behaviour = 'rechaza'
        with self.assertRaises(UserError):
            self.app.add_payment_line(
                pedido_demo.id, self.metodo_demo.id, 1200.0)
        self.assertEqual(len(pedido_demo.payment_line_ids), antes_demo)

        pedido_getnet = self._pedido_tomado()
        antes_getnet = len(pedido_getnet.payment_line_ids)
        with self.assertRaises(UserError), \
                self._soap([POSTEO_OK, DENEGADA]), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 1, 2])):
            self.app.add_payment_line(
                pedido_getnet.id, self.metodo_getnet.id, 1200.0)
        self.assertEqual(len(pedido_getnet.payment_line_ids), antes_getnet)
        self.assertEqual(pedido_getnet.state, 'tomado')

    # ==================================================================
    # PAR 3 · «no sé» -> pendiente -> Consultar lo resuelve
    # ==================================================================
    def test_par_sin_respuesta_deja_la_linea_pendiente(self):
        """
        El caso caro del §1.4: no se descarta nada, la línea queda PENDIENTE
        con su referencia para poder preguntar después.
        """
        pedido_demo = self._pedido_tomado()
        linea_demo = self._cobrar_demo(pedido_demo, 'no_responde')

        pedido_getnet = self._pedido_tomado()
        linea_getnet = self._cobrar_getnet(
            pedido_getnet, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])

        self.assertEqual(linea_demo.integration_state, 'pendiente')
        self.assertEqual(linea_getnet.integration_state,
                         linea_demo.integration_state)
        self.assertTrue(linea_getnet.transaction_reference)

    def test_consultar_resuelve_la_pendiente_de_getnet(self):
        """La salida del bloqueo del §7.2, por la puerta que usa el cajero."""
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])
        self.assertEqual(linea.integration_state, 'pendiente')

        with self._soap([APROBADA]), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 1])):
            respuesta = self.app.query_transaction(linea.id)
        self.assertEqual(respuesta['result'], 'aprobada')
        self.assertEqual(linea.integration_state, 'autorizado')
        self.assertEqual(linea.transaction_id, '7001')

    # ==================================================================
    # PAR 4 · liberar con cobro aprobado -> reversa
    # ==================================================================
    def test_par_liberar_con_cobro_aprobado_reversa_en_ambos(self):
        """
        §8.2: liberar consulta y reversa lo aprobado. La línea NO se borra:
        queda cancelada y marcada como reversada.
        """
        pedido_demo = self._pedido_tomado()
        linea_demo = self._cobrar_demo(pedido_demo, 'aprueba')
        pedido_demo.action_release()

        pedido_getnet = self._pedido_tomado()
        linea_getnet = self._cobrar_getnet(
            pedido_getnet, [POSTEO_OK, APROBADA], [0, 1, 2])
        # Aprobada: la reversa de Getnet sobre algo aprobado es un DEV.
        with self._soap([POSTEO_OK, APROBADA]), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 1, 2])):
            pedido_getnet.action_release()

        for linea in (linea_demo, linea_getnet):
            self.assertEqual(linea.state, 'cancelado')
            self.assertEqual(linea.integration_state, 'reversado')
        self.assertEqual(pedido_demo.state, 'pendiente_cobro')
        self.assertEqual(pedido_getnet.state, 'pendiente_cobro')

    # ==================================================================
    # El cron que recoge lo aprobado sin dueño
    # ==================================================================
    def test_el_cron_reversa_un_cobro_aprobado_sobre_linea_cancelada(self):
        """
        El hueco que ninguna pantalla cubre: la transacción quedó en «no sé»,
        la línea se descartó, y el cron del núcleo la resolvió APROBADA
        después. Hay plata cobrada contra una línea que ya no cuenta.
        """
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])
        self.assertEqual(linea.integration_state, 'pendiente')
        # El cajero descarta, creyendo que no pasó nada (§7.2).
        self.app.discard_transaction(linea.id)
        self.assertEqual(linea.integration_state, 'descartado')
        # Y después la transacción resulta aprobada.
        tx = self.env['payment.transaction'].sudo().search(
            [('getnet_pos_backend_reference', '=', linea.transaction_reference)],
            limit=1)
        # Con su ticket, como la dejaría la consulta que la aprueba: es el
        # único identificador con el que se puede pedir una reversa.
        tx.getnet_ticket = '7001'
        tx._set_done()

        with self._soap([POSTEO_OK, APROBADA]), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 1, 2])):
            self.env['payment.transaction'].sudo(
            )._getnet_cron_reversar_huerfanas_pos_backend()

        linea.invalidate_recordset()
        self.assertEqual(linea.integration_state, 'reversado')
        self.assertEqual(tx.getnet_pos_backend_line_id, linea)

    def _huerfana_aprobada(self, ticket):
        """Línea descartada cuya transacción resultó APROBADA después."""
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])
        self.app.discard_transaction(linea.id)
        tx = self.env['payment.transaction'].sudo().search(
            [('getnet_pos_backend_reference', '=', linea.transaction_reference)],
            limit=1)
        tx.getnet_ticket = ticket
        tx._set_done()
        return linea, tx

    def test_una_devolucion_previa_no_se_duplica(self):
        """
        Ya hubo un intento de devolución de este cobro (Odoo se reinició en
        el medio y la DEV quedó sin confirmar). Crear OTRA con la misma
        referencia reventaba con IntegrityError — y además es exactamente el
        reintento a ciegas que el §7.3 prohíbe: una devolución repetida regala
        el importe. Va a conciliación y NO se habla con la terminal. Visto
        contra el concentrador simulado el 27/09/2026.
        """
        linea, tx = self._huerfana_aprobada('7101')
        previa = self.env['payment.transaction'].sudo().create({
            'provider_id': self.provider.id,
            'payment_method_id': self.env.ref(
                'odoo_pos_getnet_core.payment_method_getnet').id,
            'reference': 'GETNET-PB-DEV-%s' % tx.reference,
            'amount': tx.amount,
            'currency_id': tx.currency_id.id,
            'partner_id': tx.partner_id.id,
            'getnet_transaction_origin': 'pos_backend',
        })
        previa._set_canceled()
        # Sin mockear el SOAP: si intentara hablar, explotaría.
        self.env['payment.transaction'].sudo(
        )._getnet_cron_reversar_huerfanas_pos_backend()
        tx.invalidate_recordset()
        self.assertTrue(tx.getnet_requiere_conciliacion)
        self.assertIn('intento de devolución', tx.getnet_motivo_conciliacion)
        self.assertEqual(self.env['payment.transaction'].sudo().search_count(
            [('reference', '=', 'GETNET-PB-DEV-%s' % tx.reference)]), 1)

    def test_una_huerfana_que_explota_no_frena_a_las_demas(self):
        """
        El cron recorre las candidatas por antigüedad: si la primera revienta
        y corta la pasada, encabeza la fila la vez siguiente y NINGUNA otra
        huérfana se reversa nunca más. Cada una se procesa aislada.
        """
        linea_mala, tx_mala = self._huerfana_aprobada('7201')
        linea_buena, tx_buena = self._huerfana_aprobada('7202')
        self.env.cr.execute(
            "UPDATE payment_transaction SET write_date = write_date - interval '1 hour' "
            "WHERE id = %s", (tx_mala.id,))
        tx_mala.invalidate_recordset()
        Tx = type(self.env['payment.transaction'])
        original = Tx._getnet_reversar_huerfana

        def reversar(modelo, tx, linea):
            if tx == tx_mala:
                raise RuntimeError('falla inesperada de prueba')
            return original(modelo, tx, linea)

        with patch.object(Tx, '_getnet_reversar_huerfana', reversar), \
                self._soap([POSTEO_OK, APROBADA]), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 1, 2])):
            self.env['payment.transaction'].sudo(
            )._getnet_cron_reversar_huerfanas_pos_backend()
        linea_buena.invalidate_recordset()
        tx_mala.invalidate_recordset()
        self.assertEqual(linea_buena.integration_state, 'reversado')
        self.assertTrue(tx_mala.getnet_requiere_conciliacion)
        self.assertIn('error inesperado', tx_mala.getnet_motivo_conciliacion)

    def test_una_aprobada_sin_ticket_va_a_conciliacion_y_no_a_ciegas(self):
        """
        Sin ticket no hay con qué pedir la reversa. Antes esto terminaba en un
        «no se encontró la transacción» que no decía nada; ahora lo dice tal
        cual y lo mira una persona.
        """
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])
        self.app.discard_transaction(linea.id)
        tx = self.env['payment.transaction'].sudo().search(
            [('getnet_pos_backend_reference', '=', linea.transaction_reference)],
            limit=1)
        self.assertFalse(tx.getnet_ticket)
        tx._set_done()

        # Sin mockear el SOAP: si intentara hablar, explotaría.
        self.env['payment.transaction'].sudo(
        )._getnet_cron_reversar_huerfanas_pos_backend()

        tx.invalidate_recordset()
        self.assertTrue(tx.getnet_requiere_conciliacion)
        self.assertIn('ticket', tx.getnet_motivo_conciliacion)

    def _aprobada_sin_linea(self, minutos):
        """Cobro APROBADO cuya línea nunca llegó a guardarse (kill de Odoo)."""
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': self.provider.id,
            'payment_method_id': self.env.ref(
                'odoo_pos_getnet_core.payment_method_getnet').id,
            'reference': 'GETNET-PB-SINLINEA-%s' % uuid.uuid4().hex[:8],
            'amount': 1200.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'getnet_transaction_origin': 'pos_backend',
            'getnet_pos_backend_reference': 'POS/Local E2E/%s-1' % uuid.uuid4().hex[:6],
            'getnet_ticket': '321',
            'getnet_terminal_id': self.terminal.id,
        })
        tx._set_done()
        tx.flush_recordset()
        self.env.cr.execute(
            "UPDATE payment_transaction SET write_date = "
            "(now() AT TIME ZONE 'UTC') - %s * interval '1 minute' WHERE id = %s",
            (minutos, tx.id))
        tx.invalidate_recordset()
        return tx

    def test_una_aprobada_sin_linea_vieja_va_a_conciliacion(self):
        """
        Odoo murió a mitad del cobro, ANTES de guardar la línea: el cron de
        recuperación la resolvió APROBADA y no hay línea que la explique. El
        cajero, que no vio nada, cobra de nuevo. Pasado el margen, la
        transacción tiene que llegar a «requieren conciliación» —la mira una
        persona— y no quedar salteada para siempre. Visto contra el
        concentrador simulado el 27/09/2026.
        """
        tx = self._aprobada_sin_linea(minutos=45)
        # Sin mockear el SOAP: NO se reversa a ciegas, sólo se marca.
        self.env['payment.transaction'].sudo(
        )._getnet_cron_reversar_huerfanas_pos_backend()
        tx.invalidate_recordset()
        self.assertTrue(tx.getnet_requiere_conciliacion)
        self.assertIn('línea', tx.getnet_motivo_conciliacion)

    def test_una_aprobada_sin_linea_reciente_se_espera(self):
        """Recién aprobada: el POS puede estar todavía guardando la línea."""
        tx = self._aprobada_sin_linea(minutos=1)
        self.env['payment.transaction'].sudo(
        )._getnet_cron_reversar_huerfanas_pos_backend()
        tx.invalidate_recordset()
        self.assertFalse(tx.getnet_requiere_conciliacion)

    # ------------------------------------------------------------------
    # Cobro automático: consultas cortas y la línea al día sola
    # ------------------------------------------------------------------
    def _linea_pendiente(self):
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])
        self.assertEqual(linea.integration_state, 'pendiente')
        tx = self.env['payment.transaction'].sudo().search(
            [('getnet_pos_backend_reference', '=', linea.transaction_reference)],
            limit=1)
        return linea, tx

    def test_la_consulta_del_pos_es_corta_y_nunca_cancela(self):
        """
        La pantalla consulta sola cada pocos segundos, y Consultar, liberar
        y cerrar la caja usan la misma operación: tiene que ser una vuelta
        corta del motor, nunca la espera de 180 s en una sola llamada (que
        trababa la pantalla y chocaba con limit_time_real), y nunca puede
        cancelar un cobro que la clienta está por aprobar.
        """
        linea, tx = self._linea_pendiente()
        Tx = type(self.env['payment.transaction'])
        original = Tx.getnet_run_query_loop
        cotas = []

        def espia(modelo, driver, token, **kw):
            cotas.append(kw)
            return original(modelo, driver, token, **kw)

        metodos = []

        def soap(prov, metodo, params):
            metodos.append(metodo)
            return (dict(EN_PROCESO), '<req/>', '<resp/>')

        with patch.object(Tx, 'getnet_run_query_loop', espia), \
                patch.object(type(self.provider), '_getnet_soap_transaccion', soap), \
                patch.object(pt_mod, 'time', _RelojDeLaboratorio(list(range(0, 400, 3)))):
            respuesta = self.app.query_transaction(linea.id)
        self.assertEqual(respuesta['result'], 'desconocida')
        self.assertTrue(cotas)
        self.assertLessEqual(cotas[0]['hard_max'], 10)
        self.assertTrue(cotas[0]['commit_por_consulta'])
        self.assertNotIn('CancelarTransaccion', metodos)

    def test_el_cron_deja_al_dia_la_linea_que_esperaba_aprobada(self):
        """Pasado el tope del sondeo, el cron resuelve y la línea se entera sola."""
        linea, tx = self._linea_pendiente()
        tx.getnet_ticket = '7301'
        tx._set_done()
        self.env['payment.transaction'].sudo(
        )._getnet_sincronizar_lineas_pos_backend()
        linea.invalidate_recordset()
        self.assertEqual(linea.integration_state, 'autorizado')
        self.assertEqual(linea.transaction_id, '7301')

    def test_el_cron_deja_al_dia_la_linea_que_esperaba_rechazada(self):
        linea, tx = self._linea_pendiente()
        tx._set_canceled(state_message='CANCELADA(LA TARJETA ESTA VENCIDA)')
        tx.getnet_msg_respuesta = 'CANCELADA(LA TARJETA ESTA VENCIDA)'
        self.env['payment.transaction'].sudo(
        )._getnet_sincronizar_lineas_pos_backend()
        linea.invalidate_recordset()
        self.assertEqual(linea.integration_state, 'descartado')
        self.assertIn('VENCIDA', linea.discard_reason)

    def test_el_cron_no_toca_una_linea_viva(self):
        """Un cobro legítimo en curso no es una huérfana."""
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK, APROBADA], [0, 1, 2])
        self.assertEqual(linea.integration_state, 'autorizado')
        # Sin mockear el SOAP: si intentara reversar, explotaría.
        self.env['payment.transaction'].sudo(
        )._getnet_cron_reversar_huerfanas_pos_backend()
        linea.invalidate_recordset()
        self.assertEqual(linea.integration_state, 'autorizado')

    def test_si_la_reversa_del_cron_falla_queda_para_conciliar(self):
        """
        No se reintenta a ciegas: una devolución repetida regala el importe
        (contrato §7.3). Se marca y sale del circuito automático.
        """
        pedido = self._pedido_tomado()
        linea = self._cobrar_getnet(
            pedido, [POSTEO_OK] + [EN_PROCESO] * 8, [0, 1, 100, 200])
        self.app.discard_transaction(linea.id)
        tx = self.env['payment.transaction'].sudo().search(
            [('getnet_pos_backend_reference', '=', linea.transaction_reference)],
            limit=1)
        tx.getnet_ticket = '7002'
        tx._set_done()

        rechazo = {'Resp_CodigoRespuesta': '2',
                   'Resp_MensajeError': 'TRANSACCION NO ENCONTRADA'}
        with self._soap([rechazo]):
            self.env['payment.transaction'].sudo(
            )._getnet_cron_reversar_huerfanas_pos_backend()

        tx.invalidate_recordset()
        self.assertTrue(tx.getnet_requiere_conciliacion)
        self.assertIn('reversa falló', tx.getnet_motivo_conciliacion)
        linea.invalidate_recordset()
        self.assertEqual(linea.integration_state, 'descartado')
