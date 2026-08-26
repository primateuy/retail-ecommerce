# -*- coding: utf-8 -*-
"""
payment.transaction extendida para Getnet/TransAct + motor de polling.

Ciclo TransAct WS (manual WS, "Secuencia de Invocación"):
  PostearTransaccion -> TokenNro -> ConsultarTransaccion en loop hasta
  Resp_TransaccionFinalizada -> persistir TransaccionId/Ticket/Lote/
  NroAutorizacion.

Semántica de confirmación: la consulta "implica" la confirmación, pero esta
se materializa recién al obtener la respuesta final aprobada — se puede
cancelar una transacción "en proceso" (precondición de CancelarTransaccion).
Por eso el polling arranca APENAS el posteo devuelve token, respetando
TokenSegundosConsultar; la regla de "estar listos para persistir" aplica al
manejo de la respuesta final, no al inicio del loop.
"""

import json
import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import getnet_utils
from .getnet_pos_terminal import GETNET_HEARTBEAT_SECONDS

_logger = logging.getLogger(__name__)

# Timeout general sugerido por el manual: 2 a 3 minutos.
GETNET_POLL_TIMEOUT_GENERAL = 180
# Tope absoluto del loop cuando la cancelación falla y seguimos consultando
# (obs. carrera timeout->cancelar->aprobada). Superado esto la transacción
# queda 'pending' para conciliación manual, NUNCA 'error'.
GETNET_POLL_HARD_MAX = 900
# Espera por defecto si el server no indica TokenSegundosConsultar.
GETNET_POLL_DEFAULT_WAIT = 5
# Cota superior a la espera entre consultas (el manual pide invocaciones de
# no más de ~15 segundos).
GETNET_POLL_MAX_WAIT = 15
# Cotas del cron de recuperación: bounds más cortos que el flujo online —
# el flujo original ya murió (nadie va a confirmar en la UI), y si no se
# resuelve en esta pasada, el cron reintenta en la siguiente.
GETNET_RECOVERY_TIMEOUT_GENERAL = 60
GETNET_RECOVERY_HARD_MAX = 300
GETNET_RECOVERY_BATCH = 20
# Pasadas del cron sobre la MISMA transacción antes de darla por no
# recuperable automáticamente. Sin este corte, una transacción que el
# concentrador nunca resuelve (o que responde siempre lo mismo) se
# re-consulta cada 5 minutos para siempre, gastando el lock de la terminal
# y escondiendo el problema en el log.
GETNET_RECOVERY_MAX_INTENTOS = 3


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    getnet_token = fields.Char(
        string='Token TransAct',
        index=True,
        copy=False,
        help='TokenNro devuelto por PostearTransaccion; identifica la '
             'factura posteada en el concentrador.',
    )
    getnet_terminal_id = fields.Many2one(
        comodel_name='getnet.pos.terminal',
        string='Terminal Getnet',
        copy=False,
    )
    getnet_transaccion_id = fields.Char(
        string='TransaccionId',
        copy=False,
    )
    getnet_ticket = fields.Char(
        string='Ticket',
        copy=False,
        help='Número de ticket asignado a la transacción. Necesario para '
             'devoluciones (TicketOriginal).',
    )
    getnet_lote = fields.Char(
        string='Lote',
        copy=False,
        help='Número de lote asignado; se concilia en el cierre de lote.',
    )
    getnet_nro_autorizacion = fields.Char(
        string='Nro. de autorización',
        copy=False,
    )
    getnet_tarjeta_id = fields.Char(
        string='Tarjeta (Id)',
        copy=False,
        help='Id de sello según tabla TarjetaId del manual general.',
    )
    getnet_tarjeta_tipo = fields.Char(
        string='Tipo de tarjeta',
        copy=False,
        help='CRE (crédito) / DEB (débito).',
    )
    getnet_cuotas = fields.Integer(
        string='Cuotas',
        copy=False,
    )
    getnet_es_offline = fields.Boolean(
        string='Autorizada offline',
        copy=False,
    )
    getnet_estado_avance = fields.Integer(
        string='Estado de avance',
        copy=False,
        help='Resp_EstadoAvance de la última consulta (0-6).',
    )
    getnet_cod_respuesta = fields.Char(
        string='Código de respuesta',
        copy=False,
        help='CodRespuesta del autorizador para la transacción.',
    )
    getnet_msg_respuesta = fields.Char(
        string='Mensaje de respuesta',
        copy=False,
    )
    getnet_voucher = fields.Text(
        string='Voucher',
        copy=False,
        help='Líneas del voucher entregadas por TransAct '
             '(Respuesta.Voucher), una por renglón.',
    )
    getnet_transaction_origin = fields.Selection(
        selection=[
            ('pos_payment', 'Pago POS'),
            ('pos_order', 'Orden POS'),
            ('account_payment', 'Pago contable'),
            ('other', 'Otro'),
        ],
        string='Origen Getnet',
        copy=False,
    )
    getnet_requiere_conciliacion = fields.Boolean(
        string='Requiere conciliación manual',
        index=True,
        copy=False,
        help='La transacción no se puede resolver automáticamente: el cron '
             'de recuperación la excluye y alguien tiene que verificarla '
             'contra el POS.',
    )
    getnet_motivo_conciliacion = fields.Char(
        string='Motivo de conciliación',
        copy=False,
    )
    getnet_recovery_intentos = fields.Integer(
        string='Intentos de recuperación',
        copy=False,
        help='Pasadas del cron de recuperación sobre esta transacción.',
    )
    getnet_complete_request = fields.Text(
        string='Request completo',
        copy=False,
        help='Auditoría: último request SOAP relevante enviado.',
    )
    getnet_complete_response = fields.Text(
        string='Response completo',
        copy=False,
        help='Auditoría: última respuesta SOAP relevante recibida.',
    )

    # ------------------------------------------------------------------
    # Motor de polling
    # ------------------------------------------------------------------
    def getnet_run_query_loop(self, driver, token, terminal=None,
                              initial_wait=None,
                              timeout_general=GETNET_POLL_TIMEOUT_GENERAL,
                              hard_max=GETNET_POLL_HARD_MAX):
        """
        Bucle ConsultarTransaccion hasta resolución. Contrato del driver:
        ``_getnet_soap_transaccion(method, params) -> (data, req, resp)``
        (lo cumple payment.provider; en fases siguientes cualquier otro
        modelo que lo exponga sirve igual).

        Reglas:
        - Arranca a consultar de inmediato tras el posteo, respetando la
          espera que indica el server (TokenSegundosConsultar /
          Resp_TokenSegundosReConsultar).
        - Es obligación del integrador consultar hasta obtener respuesta
          (manual WS): los errores de transporte NO cortan el loop.
        - Al vencer ``timeout_general`` se intenta CancelarTransaccion UNA
          vez. Si el cancel falla (p.ej. la transacción ya fue aprobada en
          el POS: solo se cancelan pendientes/en proceso), se SIGUE
          consultando hasta ``hard_max`` y se persiste la respuesta que
          venga. Nunca se marca la transacción como fallida solo porque
          venció el timeout local: perder ese caso es un cobro real en el
          pinpad sin pago registrado en Odoo.

        :return: dict con 'data' (última respuesta), 'request_xml',
                 'response_xml', 'timeout' (bool: se agotó hard_max sin
                 respuesta final) y 'cancel_attempted'/'cancel_ok'.
        """
        self.ensure_one()
        start = time.monotonic()
        wait = initial_wait or GETNET_POLL_DEFAULT_WAIT
        cancel_attempted = False
        cancel_ok = False
        data, req_xml, resp_xml = {}, '', ''
        while True:
            time.sleep(min(max(wait, 1), GETNET_POLL_MAX_WAIT))
            if terminal:
                # Mantiene vivo el lock de la terminal mientras el flujo
                # sigue en curso (aunque el polling se extienda).
                terminal.getnet_touch()
            data, req_xml, resp_xml = driver._getnet_soap_transaccion(
                'ConsultarTransaccion', {'TokenNro': token})
            rc = getnet_utils.getnet_rc(data)
            estado = getnet_utils.getnet_estado_avance(data)
            finalizado = getnet_utils.getnet_finalizado(data)
            if rc == getnet_utils.GETNET_RC_TRANSPORTE:
                _logger.warning(
                    'Getnet token %s: error de transporte en consulta, se '
                    'reintenta (%s).', token, data.get('Resp_MensajeError'))
            elif finalizado or estado in getnet_utils.ESTADOS_FINALES:
                return {
                    'data': data,
                    'request_xml': req_xml,
                    'response_xml': resp_xml,
                    'timeout': False,
                    'cancel_attempted': cancel_attempted,
                    'cancel_ok': cancel_ok,
                }
            elapsed = time.monotonic() - start
            if not cancel_attempted and elapsed >= timeout_general:
                cancel_attempted = True
                cancel_data, _creq, _cresp = driver._getnet_soap_transaccion(
                    'CancelarTransaccion', {'TokenNro': token})
                cancel_ok = (
                    getnet_utils.getnet_rc(cancel_data)
                    == getnet_utils.GETNET_RC_OK
                )
                if cancel_ok:
                    _logger.info(
                        'Getnet token %s: timeout general (%ss), cancelación '
                        'enviada OK; se consulta el estado final.',
                        token, timeout_general)
                else:
                    _logger.warning(
                        'Getnet token %s: timeout general (%ss) pero la '
                        'cancelación FALLÓ (%s) — posible transacción ya '
                        'aprobada en el POS; se sigue consultando hasta '
                        'obtener la respuesta real.',
                        token, timeout_general,
                        cancel_data.get('Resp_MensajeError'))
                # En ambos casos seguimos consultando: tras un cancel OK la
                # próxima consulta devuelve el estado CANCELADA consistente.
            if elapsed >= hard_max:
                _logger.error(
                    'Getnet token %s: sin respuesta final tras %ss; la '
                    'transacción queda pendiente para conciliación manual '
                    '(NO se marca como error).', token, hard_max)
                return {
                    'data': data,
                    'request_xml': req_xml,
                    'response_xml': resp_xml,
                    'timeout': True,
                    'cancel_attempted': cancel_attempted,
                    'cancel_ok': cancel_ok,
                }
            wait = getnet_utils.getnet_segundos_reconsulta(
                data, GETNET_POLL_DEFAULT_WAIT)

    # ------------------------------------------------------------------
    # Post-procesamiento nativo
    # ------------------------------------------------------------------
    def _create_payment(self, **extra_create_values):
        """
        Getnet NUNCA auto-crea un account.payment.

        ``account_payment._reconcile_after_done()`` llama a este método para
        toda transacción ``done`` sin ``payment_id``, y crea + postea un
        pago. Nuestras transacciones cumplen esa condición, pero el pago ya
        existe o no corresponde:

        - Flujo contable: el account.payment es el que originó el cobro y
          lo confirma el usuario a mano (nunca auto-post). Dejar que el
          core cree otro duplica el importe en los libros.
        - Flujo TPV: el cobro está representado por el pos.payment de la
          orden; un account.payment extra sería un pago fantasma.

        Detectado en staging con Fiserv instalado: su override de
        ``_create_payment`` interceptaba la llamada y la salteaba, tapando
        el problema. En una instalación standalone de Getnet —el escenario
        principal— el pago duplicado se crea.
        """
        self.ensure_one()
        if self.provider_code == 'getnet':
            pago = self.env['account.payment']
            if 'getnet_account_payment_id' in self._fields:
                pago = self.getnet_account_payment_id
            _logger.info(
                'Getnet: no se crea account.payment automático para la '
                'transacción %s (pago propio: %s).',
                self.reference, pago.id or 'ninguno')
            return pago
        return super()._create_payment(**extra_create_values)

    # ------------------------------------------------------------------
    # Conciliación manual
    # ------------------------------------------------------------------
    def getnet_marcar_conciliacion(self, motivo):
        """
        Saca la transacción del circuito automático.

        Una transacción marcada así queda FUERA del cron de recuperación:
        el cron solo sirve para lo que se puede resolver re-consultando, y
        re-consultar algo que ya dio una respuesta final irresoluble (o que
        no se resolvió en N pasadas) es un bucle infinito que además pisa
        el lock de la terminal cada 5 minutos. La resolución pasa a ser
        humana, con el filtro «Requiere conciliación» como bandeja.
        """
        self.ensure_one()
        # sudo: la marca la pone la máquina (worker o cron), no el usuario.
        self.sudo().write({
            'getnet_requiere_conciliacion': True,
            'getnet_motivo_conciliacion': motivo,
        })
        _logger.error(
            'Getnet: la transacción %s (token %s) requiere conciliación '
            'manual: %s', self.reference, self.getnet_token, motivo)

    def getnet_action_conciliada(self):
        """
        Marca como conciliada a mano: vuelve al circuito normal.

        El core solo da ACL de payment.transaction a base.group_system, y
        nuestro ACL suma lectura para contabilidad, así que la escritura va
        en sudo. Como sudo saltea el ACL, la restricción real es esta
        guarda: solo contabilidad puede dar por conciliada una transacción
        (ocultar el botón en la vista no alcanza, se llega también por RPC).
        """
        if not self.env.su and not self.env.user.has_group(
                'account.group_account_user'):
            raise AccessError(_(
                'Solo un usuario de Contabilidad puede marcar una '
                'transacción Getnet como conciliada.'))
        self.sudo().write({
            'getnet_requiere_conciliacion': False,
            'getnet_recovery_intentos': 0,
        })
        return True

    # ------------------------------------------------------------------
    # Persistencia del resultado
    # ------------------------------------------------------------------
    def getnet_persist_query_result(self, result):
        """
        Persiste el resultado del loop y transiciona el estado de la
        transacción con los helpers nativos de payment.transaction.

        Mapeo:
        - timeout (hard_max agotado)      -> _set_pending() + warning
        - EstadoAvance CANCELADA          -> _set_canceled()
        - Aprobada = true                 -> _set_done()
        - finalizada y no aprobada        -> _set_error()
        """
        self.ensure_one()
        data = result.get('data') or {}
        # Voucher es un ArrayOfstring: el parser lo entrega como lista de
        # renglones bajo la clave 'Voucher'.
        voucher = data.get('Voucher')
        if isinstance(voucher, list):
            voucher = '\n'.join(voucher)
        # CodRespAdq es el nombre del contrato para el código del
        # autorizador (CodRespuesta solo existe en el servicio de cierre).
        cod_respuesta = data.get('CodRespAdq') or data.get('CodRespuesta')
        # Lote='0' del concentrador significa "sin lote", no lote cero.
        lote = getnet_utils.getnet_lote_valido(data.get('Lote'))
        vals = {
            'getnet_transaccion_id': data.get('TransaccionId') or self.getnet_transaccion_id,
            'getnet_ticket': data.get('Ticket') or self.getnet_ticket,
            'getnet_lote': lote or self.getnet_lote,
            'getnet_nro_autorizacion': data.get('NroAutorizacion') or self.getnet_nro_autorizacion,
            'getnet_tarjeta_id': data.get('TarjetaId') or self.getnet_tarjeta_id,
            'getnet_tarjeta_tipo': data.get('TarjetaTipo') or self.getnet_tarjeta_tipo,
            'getnet_es_offline': getnet_utils.getnet_bool(data, 'EsOffline'),
            'getnet_estado_avance': getnet_utils.getnet_estado_avance(data),
            'getnet_cod_respuesta': cod_respuesta or self.getnet_cod_respuesta,
            'getnet_msg_respuesta': data.get('MsgRespuesta') or data.get('Resp_MensajeError') or self.getnet_msg_respuesta,
            'getnet_voucher': voucher or self.getnet_voucher,
            'getnet_complete_request': result.get('request_xml') or self.getnet_complete_request,
            'getnet_complete_response': result.get('response_xml') or self.getnet_complete_response,
        }
        cuotas = data.get('Cuotas')
        if cuotas:
            try:
                vals['getnet_cuotas'] = int(cuotas)
            except (TypeError, ValueError):
                pass
        self.write(vals)

        estado = getnet_utils.getnet_estado_avance(data)
        aprobada = getnet_utils.getnet_bool(data, 'Aprobada')
        msg = data.get('MsgRespuesta') or data.get('Resp_MensajeError') or ''
        # "Finalizada" NO es "exitosa": FINALIZADA_ERROR y CANCELADA son
        # estados finales de fracaso. Si además llega Aprobada=true, la
        # respuesta se contradice y no se resuelve en ningún sentido: ni
        # done (registraría un cobro que el estado desmiente) ni error
        # (declararía fallido un posible cobro real). Queda pendiente para
        # conciliación manual, igual que un timeout.
        estado_de_fracaso = estado in (
            getnet_utils.ESTADOAVANCE_FINALIZADA_ERROR,
            getnet_utils.ESTADOAVANCE_CANCELADA,
        )
        contradictoria = aprobada and estado_de_fracaso

        # Lote en Abierto con el Lote de cada transacción aprobada
        # (patrón del manual para integrar totales de cierre).
        if (aprobada and not contradictoria
                and lote and self.getnet_terminal_id):
            self.env['getnet.lote.cierre'].getnet_upsert_lote_abierto(
                self.getnet_terminal_id, self.provider_id, lote)

        if result.get('timeout'):
            # Sin respuesta final del concentrador: puede haber cobro real
            # en el pinpad. Se deja pendiente para conciliación manual.
            self._set_pending(state_message=_(
                'Getnet: sin respuesta final del concentrador (token %s). '
                'Verificar en el POS antes de reintentar o anular.',
                self.getnet_token))
        elif contradictoria:
            # Es una respuesta FINAL: re-consultarla devolvería siempre lo
            # mismo, así que además de dejarla pendiente hay que sacarla
            # del cron o queda reintentándose cada 5 minutos para siempre.
            self._set_pending(state_message=_(
                'Getnet: respuesta contradictoria del concentrador '
                '(aprobada pero con estado final de error/cancelación). '
                'Verificar en el POS antes de registrar o anular. %s', msg))
            self.getnet_marcar_conciliacion(_(
                'Respuesta final contradictoria: Aprobada=true con estado '
                '%(estado)s. %(msg)s', estado=estado, msg=msg))
        elif estado == getnet_utils.ESTADOAVANCE_CANCELADA:
            self._set_canceled(state_message=msg or _('Cancelada en TransAct.'))
            self.getnet_action_conciliada()
        elif aprobada:
            self._set_done(state_message=msg)
            self.getnet_action_conciliada()
        else:
            self._set_error(_(
                'Getnet: transacción no aprobada. %(code)s %(msg)s',
                code=cod_respuesta or '', msg=msg))
            self.getnet_action_conciliada()
        return self.state

    # ------------------------------------------------------------------
    # Cron de recuperación de transacciones en vuelo
    # ------------------------------------------------------------------
    @api.model
    def _getnet_cron_recover_inflight(self):
        """
        Recupera transacciones en vuelo cuyo hilo de polling murió (restart
        de Odoo, deploy, worker caído) o que quedaron 'pending' por el tope
        duro del loop: las re-consulta con el mismo motor hasta resolverlas.
        Unifica la recuperación en un solo mecanismo y deja la conciliación
        manual como excepción verdadera.

        Concurrencia cron vs hilo vivo: un hilo vivo hace touch del lock de
        la terminal en cada iteración (<=15s); si el lock de la terminal
        pertenece al token de la transacción y su touch es reciente
        (heartbeat), el cron la saltea. Un lock del propio token con
        heartbeat vencido es de un worker muerto: se libera y se re-toma
        como 'recovery' sin esperar el TTL completo. Una terminal tomada
        por OTRA operación viva hace saltear la transacción hasta la
        próxima pasada.

        El cron NO es infinito: solo recupera lo que se puede resolver
        re-consultando. Las transacciones marcadas
        ``getnet_requiere_conciliacion`` quedan fuera, y una transacción
        que sobrevive GETNET_RECOVERY_MAX_INTENTOS pasadas sin resolverse
        (típicamente la que agotó el hard-max del loop una y otra vez) se
        marca y sale del circuito automático.
        """
        candidatas = self.search([
            ('provider_id.code', '=', 'getnet'),
            ('state', 'in', ('draft', 'pending')),
            ('getnet_token', '!=', False),
            ('getnet_requiere_conciliacion', '=', False),
        ], limit=GETNET_RECOVERY_BATCH, order='write_date asc')
        for tx in candidatas:
            terminal = tx.getnet_terminal_id
            if terminal and terminal.getnet_heartbeat_alive(tx.getnet_token):
                # Hilo vivo consultando esta transacción: no interferir.
                continue
            if not terminal:
                # Sin terminal no hay heartbeat: dar margen a un flujo
                # recién arrancado antes de recuperar.
                edad = (fields.Datetime.now() - tx.write_date).total_seconds()
                if edad < GETNET_HEARTBEAT_SECONDS:
                    continue
            claimed = False
            if terminal:
                if (terminal.lock_origin
                        and terminal.lock_ref == tx.getnet_token):
                    # Lock del propio token con heartbeat vencido: worker
                    # muerto; se libera sin esperar el TTL del claim.
                    terminal.getnet_release()
                try:
                    terminal.getnet_claim('recovery', tx.getnet_token)
                    claimed = True
                except UserError:
                    # Terminal ocupada por otra operación viva.
                    continue
            # El intento se cuenta ANTES de ejecutarlo: si el proceso muere
            # a mitad de la recuperación, el reintento igual suma y la
            # transacción no se queda dando vueltas sin límite.
            tx.getnet_recovery_intentos += 1
            intento = tx.getnet_recovery_intentos
            getnet_utils.getnet_safe_commit(self.env)
            _logger.info(
                'Getnet recovery: recuperando transacción %s (token %s, '
                'estado %s, intento %s/%s).', tx.reference, tx.getnet_token,
                tx.state, intento, GETNET_RECOVERY_MAX_INTENTOS)
            try:
                result = tx.getnet_run_query_loop(
                    tx.provider_id, tx.getnet_token, terminal=terminal,
                    timeout_general=GETNET_RECOVERY_TIMEOUT_GENERAL,
                    hard_max=GETNET_RECOVERY_HARD_MAX)
                tx.getnet_persist_query_result(result)
                _logger.info(
                    'Getnet recovery: transacción %s resuelta a estado %s.',
                    tx.reference, tx.state)
            except Exception:
                _logger.exception(
                    'Getnet recovery: fallo recuperando la transacción %s; '
                    'se reintentará en la próxima pasada.', tx.reference)
            finally:
                if claimed:
                    terminal.getnet_release()
            # Corte de reintentos: si sigue en vuelo después del tope, el
            # cron ya no la va a resolver (el hard-max del loop se agotó
            # una y otra vez). Sale del circuito automático en vez de
            # reintentarse cada 5 minutos indefinidamente.
            if (tx.state in ('draft', 'pending')
                    and not tx.getnet_requiere_conciliacion
                    and intento >= GETNET_RECOVERY_MAX_INTENTOS):
                tx.getnet_marcar_conciliacion(_(
                    'Sin respuesta final del concentrador tras %s intentos '
                    'de recuperación. Verificar el cobro en el POS.',
                    intento))
            # Cada transacción recuperada se consolida por separado.
            getnet_utils.getnet_safe_commit(self.env)

    def getnet_log_result_json(self, result):
        """Serializa el resultado del loop para logs/auditoría puntual."""
        self.ensure_one()
        try:
            return json.dumps(result.get('data') or {}, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(result.get('data'))
