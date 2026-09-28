# -*- coding: utf-8 -*-
"""
La terminal Getnet/TransAct del POS Backend.

Implementa `pos_backend.terminal` —el contrato del Sprint 12, documentado en
`pos_backend/doc/contrato-terminales.md`— contra TransAct v4.

LA REGLA QUE GOBIERNA TODO EL ARCHIVO: los seis hooks los llama el POS DENTRO
de su propia transacción, con un pedido a medio construir. Un `commit` ahí
publicaría medio pedido. Así que todo lo que necesita quedar en firme antes de
hablarle al concentrador —el claim de la terminal y el mapeo
referencia -> token— va en un CURSOR PROPIO Y AISLADO. Y ninguna llamada espera
al pinpad más que unos segundos: la espera larga vive en el cliente (consultas
cortas a `terminal_query`) y, pasado el tope del pinpad, en el cron.

Cada hook se parte en dos: el hook, que abre el cursor, y un `_inner` que
recibe el `env` y hace el trabajo. No es ceremonia: es lo que permite probar
la lógica sincrónicamente, porque un cursor nuevo no ve los datos sin
commitear de un test.
"""

import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils
from odoo.addons.pos_backend.models.pos_backend_terminal import (
    RESULT_APPROVED,
    RESULT_REJECTED,
    RESULT_UNKNOWN,
)

_logger = logging.getLogger(__name__)

# Origen con el que se marcan nuestras transacciones. El cron de recuperación
# del núcleo es agnóstico del origen, así que hereda la red de seguridad sin
# tocar nada; esto es para poder mirarlas y para el cierre de lote.
GETNET_ORIGEN = 'pos_backend'

# La consulta que hace el POS —Consultar, el sondeo automático de la
# pantalla, liberar y cerrar la caja— es CORTA: una vuelta del motor acotada
# a pocos segundos. Nunca la espera de hasta 180 s del pinpad en una sola
# llamada: eso trababa la pantalla y chocaba con limit_time_real. La espera
# larga vive en el cliente (una llamada corta cada pocos segundos, hasta el
# timeout del pinpad) y, pasado ese tope, en el cron de recuperación.
GETNET_CONSULTA_POS_SEGUNDOS = 6

# Estado de la transacción -> una de las TRES respuestas del contrato §3.3.
# No son dos, y la diferencia es la que separa una integración que pierde
# plata de una que no: `error` es la terminal diciendo que NO —no hay nada que
# consultar después—; `pending` es no saber, y puede haber plata cobrada.
GETNET_ESTADO_A_RESULTADO = {
    'done': RESULT_APPROVED,
    'error': RESULT_REJECTED,
    'cancel': RESULT_REJECTED,
}


class PosBackendTerminalGetnet(models.AbstractModel):
    _name = 'pos_backend.terminal.getnet'
    _inherit = 'pos_backend.terminal'
    _description = 'Terminal Getnet/TransAct para el POS Backend'

    # ------------------------------------------------------------------
    # Resolución de terminal y proveedor
    # ------------------------------------------------------------------
    def _getnet_terminal(self, payment_method):
        """El pinpad de esta caja, o un error que dice qué configurar."""
        terminal = payment_method.getnet_terminal_id
        if not terminal:
            raise UserError(_(
                'El medio «%s» no tiene asignada una terminal Getnet, así '
                'que no hay a quién pedirle la autorización.',
                payment_method.name))
        # sudo: payment.provider es de base.group_system y quien cobra es un
        # cajero. Se leen el código y las credenciales para hablarle al
        # concentrador — es la máquina actuando en nombre del usuario, el
        # mismo criterio que el resto del módulo.
        return terminal.sudo()

    # ------------------------------------------------------------------
    # Cursor propio
    # ------------------------------------------------------------------
    def _getnet_en_cursor_propio(self, trabajo):
        """Corre ``trabajo(env)`` en un cursor nuevo, ajeno al del POS.

        Lo que se escriba acá sobrevive a un rollback del llamador, y lo que
        el llamador tenga sin commitear NO se ve desde adentro. Las dos cosas
        son a propósito: el claim de la terminal tiene que hacerse visible a
        los otros flujos antes de tocar el concentrador, y el pedido a medio
        construir del POS no tiene que viajar a ningún lado.
        """
        # 19.0: `odoo.registry` YA NO EXISTE — el core usa
        # `odoo.modules.registry.Registry` (ver ir_cron y mail_mail).
        from odoo.api import Environment
        from odoo.modules.registry import Registry

        registro = Registry(self.env.cr.dbname)
        with registro.cursor() as cr:
            env = Environment(cr, self.env.uid, dict(self.env.context))
            try:
                return trabajo(env)
            except Exception:
                cr.rollback()
                raise

    # ------------------------------------------------------------------
    # 1 · ¿Estás disponible?
    # ------------------------------------------------------------------
    def terminal_is_available(self, payment_method):
        """Se pregunta al ABRIR el cobro, así que no se le habla al pinpad.

        Consultarle al concentrador en cada apertura de pantalla es ruido
        sobre un equipo serial: lo que se verifica es lo que puede estar mal
        sin salir de Odoo —configuración y terminal ocupada por otro flujo—,
        que es además lo único con un motivo accionable para el cajero.
        """
        try:
            terminal = self._getnet_terminal(payment_method)
        except UserError as error:
            return {'available': False, 'reason': str(error)}
        provider = terminal.payment_provider_id
        if not provider or provider.state == 'disabled':
            return {'available': False, 'reason': _(
                'El proveedor Getnet de la terminal %s está deshabilitado.',
                terminal.display_name)}
        if terminal.lock_origin and terminal.lock_origin != GETNET_ORIGEN:
            return {'available': False, 'reason': _(
                'La terminal %(term)s está ocupada por otra operación '
                '(%(origen)s). El mismo pinpad no puede atender dos cobros a '
                'la vez.',
                term=terminal.display_name, origen=terminal.lock_origin)}
        return {'available': True, 'reason': ''}

    # ------------------------------------------------------------------
    # 2 · Autorizá este importe
    # ------------------------------------------------------------------
    def terminal_authorize(self, payment_method, amount, currency, reference):
        return self._getnet_en_cursor_propio(
            lambda env: self._getnet_authorize_inner(
                env, payment_method.id, amount, currency, reference))

    def _getnet_authorize_inner(self, env, payment_method_id, amount, currency,
                                reference):
        """Postea el cobro y espera la ventana de gracia.

        El orden no es negociable:

          1. se crea la transacción con la REFERENCIA del POS y se consolida
             —es la llave con la que el POS vuelve a preguntar—;
          2. se toma el claim de la terminal y se postea (el wrapper del
             núcleo consolida el claim antes de tocar el WS y libera en todo
             camino de error);
          3. se espera la ventana, corta y acotada, sin retener nada;
          4. se libera la terminal y se contesta una de las tres respuestas.

        Si la ventana expira se contesta «no sé» y la transacción queda
        pendiente con su token: la resuelve `terminal_query` cuando el cajero
        toque Consultar, o el cron de recuperación del núcleo si nadie lo
        toca. Nunca se contesta «rechazada» sin saber: eso descartaría una
        transacción que puede existir.
        """
        metodo = env['pos_backend.box.payment.method'].browse(payment_method_id)
        terminal = self._getnet_terminal(metodo)
        provider = terminal.payment_provider_id
        tx = env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': env.ref(
                'odoo_pos_getnet_core.payment_method_getnet').id,
            'reference': 'GETNET-PB-%s' % reference,
            'amount': amount,
            'currency_id': (currency or env.company.currency_id).id,
            # El contrato no le pasa el cliente a `terminal_authorize`, y está
            # bien que no lo haga: la terminal cobra un importe, no atiende a
            # una persona. Pero `payment.transaction.create` de 19.0 exige
            # partner_id sin defensa (`values['partner_id']`), así que va el
            # de la compañía: esta transacción es el registro TÉCNICO del
            # diálogo con el pinpad, no un documento del cliente — el cliente
            # vive en el pedido del POS, que es donde alguien lo va a buscar.
            'partner_id': env.company.partner_id.id,
            'getnet_transaction_origin': GETNET_ORIGEN,
            'getnet_pos_backend_reference': reference,
        })
        getnet_utils.getnet_safe_commit(env)
        payload = self._getnet_payload_venta(
            provider, terminal, amount, currency or env.company.currency_id)
        try:
            data, _req, _resp = provider.getnet_postear_transaccion_con_lock(
                terminal, payload, GETNET_ORIGEN, ref=reference, tx=tx)
        except Exception as error:
            _logger.exception(
                'Getnet POS Backend: falló el posteo de la referencia %s',
                reference)
            # No se pudo ni postear: no hay transacción del otro lado que
            # pueda haber pasado, pero tampoco hay certeza de eso, así que
            # se contesta «no sé» y NO «rechazada».
            tx._set_pending(state_message=str(error))
            getnet_utils.getnet_safe_commit(env)
            return {'result': RESULT_UNKNOWN, 'transaction_id': '',
                    'message': str(error)}
        rc = getnet_utils.getnet_rc(data)
        if rc == getnet_utils.GETNET_RC_TRANSPORTE:
            # 🔴 UN FALLO DE TRANSPORTE NO ES UN RECHAZO. El rc 999 lo pone
            # nuestro propio cliente SOAP cuando no hubo respuesta usable: un
            # timeout, un 502, un cable. El pedido PUDO haber llegado al
            # concentrador y haberse posteado igual, así que decir «rechazada»
            # descartaría una transacción que quizá existe — el error del
            # §3.3 del contrato, el que cuesta plata.
            #
            # Se contesta «no sé». Sin token no hay a quién consultarle, así
            # que la línea queda pendiente y visible hasta que alguien la
            # concilie: es incómodo y es lo correcto.
            mensaje = data.get('Resp_MensajeError') or ''
            tx._set_pending(state_message=_(
                'Getnet: no hubo respuesta del concentrador al postear '
                '(%(rc)s): %(msg)s', rc=rc, msg=mensaje))
            getnet_utils.getnet_safe_commit(env)
            return {'result': RESULT_UNKNOWN, 'transaction_id': '',
                    'message': mensaje or _(
                        'No se pudo confirmar si la operación llegó a la '
                        'terminal.')}
        if rc != getnet_utils.GETNET_RC_OK:
            mensaje = data.get('Resp_MensajeError') or ''
            # RECHAZO DEL POSTEO, no de la tarjeta: el concentrador CONTESTÓ y
            # dijo que no (campo inválido, comercio mal, terminal desconocida),
            # así que no hay nada en el pinpad. Acá sí se puede decir
            # «rechazada» sin riesgo.
            tx._set_error(_(
                'Getnet: el posteo fue rechazado (%(rc)s): %(msg)s',
                rc=rc, msg=mensaje))
            getnet_utils.getnet_safe_commit(env)
            return {'result': RESULT_REJECTED, 'transaction_id': '',
                    'message': mensaje or _(
                        'La terminal no aceptó la operación.')}
        try:
            self._getnet_esperar_ventana(env, tx, provider, terminal, data)
        finally:
            terminal.getnet_release()
            getnet_utils.getnet_safe_commit(env)
        return self._getnet_resultado(tx)

    def _getnet_payload_venta(self, provider, terminal, amount, currency):
        """Payload de PostearTransaccion para un cobro del POS Backend.

        FacturaNro va en 0 SIEMPRE, y no es una simplificación: en el POS el
        CFE se emite al finalizar la venta, o sea DESPUÉS de cobrar. No hay
        número de factura que mandar cuando se pide la autorización. El 0 es
        el valor que el concentrador acepta para ese caso (omitirlo devuelve
        rc=2 CAMPO REQUERIDO / FACTURA).
        """
        vals = provider._getnet_base_transaccion_vals(terminal)
        vals['MonedaISO'] = provider._getnet_moneda_iso(currency)
        vals['Operacion'] = getnet_utils.GETNET_OPERACION_VENTA
        vals['Monto'] = getnet_utils.getnet_centavos(amount)
        vals['FacturaNro'] = getnet_utils.GETNET_FACTURA_NRO_SIN_FACTURA
        if provider.getnet_modo_emulacion:
            vals['Configuracion'] = {'ModoEmulacion': True}
        # DecretoLeyId NO se setea: comportamiento recomendado del manual, el
        # POS se lo solicita al cajero en el pinpad.
        return vals

    def _getnet_esperar_ventana(self, env, tx, provider, terminal, post_data):
        """La ventana de gracia: el MISMO motor de polling, acotado.

        Los cinco invariantes que la gobiernan están escritos en
        `getnet_run_query_loop`, que es donde vive el mecanismo. Acá sólo se
        elige la cota, y el `commit_por_consulta` es lo que hace que el sleep
        de cada vuelta pase con la transacción ya consolidada.

        `timeout_general` se deja en su valor normal a propósito: la ventana
        vence MUCHÍSIMO antes, así que nunca se llega a CancelarTransaccion.
        Cancelar un cobro que la clienta está por aprobar sería lo peor que
        este código podría hacer.
        """
        ventana = provider.getnet_ventana_autorizacion
        if ventana <= 0:
            # Ventana apagada: se contesta «no sé» y manda la consulta. Es un
            # camino legítimo del contrato, no una degradación.
            return None
        result = tx.getnet_run_query_loop(
            provider, tx.getnet_token, terminal=terminal,
            initial_wait=getnet_utils.getnet_segundos_reconsulta(post_data, 1),
            hard_max=ventana,
            commit_por_consulta=True)
        tx.getnet_persist_query_result(result)
        getnet_utils.getnet_safe_commit(env)
        return result

    # ------------------------------------------------------------------
    # 3 · ¿Qué pasó con esta transacción?
    # ------------------------------------------------------------------
    def terminal_query(self, payment_method, reference):
        return self._getnet_en_cursor_propio(
            lambda env: self._getnet_query_inner(
                env, payment_method.id, reference))

    def _getnet_query_inner(self, env, payment_method_id, reference):
        """LA OPERACIÓN QUE EVITA EL CASO CARO (contrato §1.4).

        CORTA A PROPÓSITO: una vuelta del motor acotada a
        GETNET_CONSULTA_POS_SEGUNDOS, sin cancelar nunca (la cota queda por
        debajo del timeout general). La llama el sondeo automático de la
        pantalla cada pocos segundos, además de Consultar, liberar y cerrar la
        caja: ninguna de esas llamadas puede durar más que unos segundos.
        """
        tx = self._getnet_tx_de_referencia(env, reference)
        if not tx:
            # Sin transacción no se puede afirmar que no pasó nada: la
            # creación misma pudo no haber quedado. «No sé» es la respuesta
            # prudente y la que deja la línea pendiente en vez de borrarla.
            return {'result': RESULT_UNKNOWN, 'transaction_id': '',
                    'message': _(
                        'No se encontró la transacción Getnet de la '
                        'referencia %s.', reference)}
        if tx.state in GETNET_ESTADO_A_RESULTADO:
            # Ya resuelta (por la ventana, por otra consulta o por el cron).
            return self._getnet_resultado(tx)
        if not tx.getnet_token:
            return {'result': RESULT_UNKNOWN, 'transaction_id': '',
                    'message': _(
                        'La transacción no llegó a tener token en el '
                        'concentrador; no hay nada que consultar.')}
        metodo = env['pos_backend.box.payment.method'].browse(payment_method_id)
        terminal = tx.getnet_terminal_id or self._getnet_terminal(metodo)
        provider = terminal.payment_provider_id
        result = tx.getnet_run_query_loop(
            provider, tx.getnet_token, terminal=terminal, initial_wait=0,
            hard_max=GETNET_CONSULTA_POS_SEGUNDOS, commit_por_consulta=True)
        tx.getnet_persist_query_result(result)
        getnet_utils.getnet_safe_commit(env)
        return self._getnet_resultado(tx)

    def _getnet_tx_de_referencia(self, env, reference):
        return env['payment.transaction'].sudo().search([
            ('getnet_pos_backend_reference', '=', reference),
            ('provider_id.code', '=', 'getnet'),
        ], limit=1, order='id desc')

    def _getnet_resultado(self, tx):
        """Traduce el estado de la transacción a las tres respuestas."""
        return {
            'result': GETNET_ESTADO_A_RESULTADO.get(tx.state, RESULT_UNKNOWN),
            'transaction_id': tx.getnet_ticket or '',
            'message': tx.getnet_msg_respuesta or '',
        }

    # ------------------------------------------------------------------
    # 4 y 5 · Reversar y devolver
    # ------------------------------------------------------------------
    def terminal_reverse(self, payment_method, transaction_id):
        return self._getnet_en_cursor_propio(
            lambda env: self._getnet_reverse_inner(
                env, payment_method.id, transaction_id))

    def _getnet_reverse_inner(self, env, payment_method_id, transaction_id):
        """Cancelar lo que todavía no se cerró.

        🔴 EN TRANSACT LA DISTINCIÓN DEL CONTRATO NO EXISTE A NIVEL DE CABLE.
        `CancelarTransaccion` sólo cancela lo pendiente o en proceso; una
        transacción YA APROBADA no se cancela, se devuelve (DEV con
        TicketOriginal). Así que este hook hace lo que corresponde según el
        estado real y no según el nombre del hook: pendiente -> cancelar,
        aprobada -> devolver.

        TODO-homologación: confirmar con New Age Data si una transacción
        aprobada y NO liquidada admite una anulación más barata que el DEV.
        Si la admitiera, acá cambia el camino de la aprobada y el POS no se
        enteraría — que es justamente la gracia de que la elección viva en el
        módulo de terminal (contrato §7.3, punto 3).
        """
        tx = self._getnet_tx_de_ticket(env, transaction_id)
        if not tx:
            return {'ok': False, 'message': _(
                'No se encontró la transacción Getnet del ticket %s.',
                transaction_id)}
        if tx.state == 'done':
            return self._getnet_refund_inner(
                env, payment_method_id, transaction_id, tx.amount)
        provider = tx.provider_id
        data, _req, _resp = provider._getnet_soap_transaccion(
            'CancelarTransaccion', {'TokenNro': tx.getnet_token})
        if getnet_utils.getnet_rc(data) != getnet_utils.GETNET_RC_OK:
            return {'ok': False,
                    'message': data.get('Resp_MensajeError') or _(
                        'El concentrador no pudo cancelar la transacción.')}
        tx._set_canceled(state_message=_('Cancelada desde el POS Backend.'))
        getnet_utils.getnet_safe_commit(env)
        return {'ok': True, 'message': _('Transacción cancelada.')}

    def terminal_refund(self, payment_method, transaction_id, amount):
        return self._getnet_en_cursor_propio(
            lambda env: self._getnet_refund_inner(
                env, payment_method.id, transaction_id, amount))

    def _getnet_refund_inner(self, env, payment_method_id, transaction_id,
                             amount):
        """DEV + TicketOriginal de la transacción original."""
        original = self._getnet_tx_de_ticket(env, transaction_id)
        if not original or not original.getnet_ticket:
            return {'ok': False, 'message': _(
                'No se encontró una transacción Getnet aprobada con el '
                'ticket %s; no hay qué devolver.', transaction_id)}
        metodo = env['pos_backend.box.payment.method'].browse(payment_method_id)
        terminal = original.getnet_terminal_id or self._getnet_terminal(metodo)
        provider = terminal.payment_provider_id
        vals = provider._getnet_base_transaccion_vals(terminal)
        vals['MonedaISO'] = provider._getnet_moneda_iso(original.currency_id)
        vals['Operacion'] = getnet_utils.GETNET_OPERACION_DEVOLUCION
        vals['Monto'] = getnet_utils.getnet_centavos(amount)
        try:
            # TicketOriginal es xs:int en el contrato aunque el Ticket llegue
            # como xs:double y se persista como texto.
            vals['TicketOriginal'] = getnet_utils.getnet_entero_contrato(
                original.getnet_ticket, 'TicketOriginal')
        except ValueError:
            return {'ok': False, 'message': _(
                'El ticket de la transacción original no es numérico '
                '(%s); no se puede enviar la devolución.',
                original.getnet_ticket)}
        if provider.getnet_modo_emulacion:
            vals['Configuracion'] = {'ModoEmulacion': True}
        # 🔴 Una devolución por cobro. Si ya hubo un intento —Odoo se reinició
        # a mitad, o la respuesta no llegó— NO se crea otro: además de
        # reventar por la referencia única, es el reintento a ciegas que el
        # §7.3 prohíbe, porque una devolución repetida regala el importe.
        referencia_dev = 'GETNET-PB-DEV-%s' % original.reference
        previa = env['payment.transaction'].sudo().search(
            [('reference', '=', referencia_dev)], limit=1)
        if previa:
            if previa.state == 'done':
                return {'ok': True, 'message': _(
                    'La devolución de este cobro ya estaba aprobada '
                    '(ticket %s).', previa.getnet_ticket or '-')}
            return {'ok': False, 'message': _(
                'Ya hubo un intento de devolución de este cobro '
                '(%(ref)s, estado %(estado)s) y no se reintenta a ciegas: una '
                'devolución repetida regala el importe. Verificarla contra '
                'el cierre del adquirente.',
                ref=referencia_dev, estado=previa.state)}
        devolucion = env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': env.ref(
                'odoo_pos_getnet_core.payment_method_getnet').id,
            'reference': referencia_dev,
            'amount': amount,
            'currency_id': original.currency_id.id,
            'partner_id': original.partner_id.id,
            'getnet_transaction_origin': GETNET_ORIGEN,
        })
        getnet_utils.getnet_safe_commit(env)
        try:
            data, _req, _resp = provider.getnet_postear_transaccion_con_lock(
                terminal, vals, GETNET_ORIGEN,
                ref=devolucion.reference, tx=devolucion)
        except Exception as error:
            _logger.exception(
                'Getnet POS Backend: falló el posteo de la devolución de %s',
                original.reference)
            return {'ok': False, 'message': str(error)}
        try:
            if getnet_utils.getnet_rc(data) != getnet_utils.GETNET_RC_OK:
                mensaje = data.get('Resp_MensajeError') or ''
                devolucion._set_error(mensaje or _('Devolución rechazada.'))
                return {'ok': False, 'message': mensaje}
            result = devolucion.getnet_run_query_loop(
                provider, devolucion.getnet_token, terminal=terminal)
            devolucion.getnet_persist_query_result(result)
        finally:
            terminal.getnet_release()
            getnet_utils.getnet_safe_commit(env)
        if devolucion.state != 'done':
            # 🔴 Una devolución de respuesta desconocida NO se reintenta sola
            # (contrato §7.3): reintentar a ciegas puede regalar el importe
            # entero. Queda registrada y se resuelve consultando.
            return {'ok': False, 'message': devolucion.getnet_msg_respuesta or _(
                'La devolución no quedó confirmada. Queda registrada con su '
                'referencia; verificala antes de reintentar.')}
        return {'ok': True, 'message': _(
            'Devolución aprobada (ticket %s).', devolucion.getnet_ticket or '-')}

    def _getnet_tx_de_ticket(self, env, transaction_id):
        """La transacción por su ticket, que es el id que devolvimos al POS."""
        if not transaction_id:
            return env['payment.transaction'].sudo()
        return env['payment.transaction'].sudo().search([
            ('getnet_ticket', '=', str(transaction_id)),
            ('provider_id.code', '=', 'getnet'),
        ], limit=1, order='id desc')

    # ------------------------------------------------------------------
    # 7 · Cerrá el lote (contrato §8.1)
    # ------------------------------------------------------------------
    def terminal_close_batch(self, payment_method, session):
        return self._getnet_en_cursor_propio(
            lambda env: self._getnet_close_batch_inner(
                env, payment_method.id, session.id))

    def _getnet_close_batch_inner(self, env, payment_method_id, session_id):
        """Cierre de lote sobre el `getnet.lote.cierre` que ya modela el núcleo.

        Con transacciones en vuelo NO SE INTENTA el cierre: el cierre de
        TransAct reversa las pendientes de confirmación, así que intentarlo
        sería resolver por la fuerza algo que todavía se puede resolver bien.
        Se informa el número y el POS bloquea el cierre de caja — la decisión
        es suya, no nuestra.
        """
        metodo = env['pos_backend.box.payment.method'].browse(payment_method_id)
        try:
            terminal = self._getnet_terminal(metodo)
        except UserError as error:
            return {'ok': False, 'in_flight': 0, 'message': str(error)}
        en_vuelo = terminal._getnet_txs_en_vuelo()
        if en_vuelo:
            return {
                'ok': False,
                'in_flight': len(en_vuelo),
                'message': _(
                    'No se intentó el cierre de lote: cerrarlo reversaría las '
                    'transacciones pendientes de confirmación (%s).',
                    ', '.join(en_vuelo.mapped('reference')[:5])),
            }
        try:
            terminal.getnet_cerrar_lote(force=False)
        except UserError as error:
            return {'ok': False, 'in_flight': 0, 'message': str(error)}
        getnet_utils.getnet_safe_commit(env)
        ultimo = env['getnet.lote.cierre'].sudo().search(
            [('terminal_id', '=', terminal.id)], limit=1, order='id desc')
        return {
            'ok': True,
            'in_flight': 0,
            'message': '',
            'batch_reference': ultimo.lote or '',
        }

    # La operación 6 (`terminal_is_settled`) NO se implementa a propósito:
    # Getnet no sabe si el adquirente liquidó, y el «no sé» que trae el
    # contrato por defecto elige DEVOLUCIÓN, que es el camino correcto por la
    # asimetría de costo del §7.3. Implementarla para devolver None sería
    # ruido.
