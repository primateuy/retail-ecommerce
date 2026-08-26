# -*- coding: utf-8 -*-
"""
payment.provider con código 'getnet': credenciales TransAct y capa SOAP.

El provider es el "driver" del motor de polling (contrato mínimo:
_getnet_soap_transaccion). En fases siguientes pos.payment.method podrá
delegar siempre en el provider — a diferencia de Fiserv no duplicamos
credenciales por método de pago.
"""

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from . import getnet_utils

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('getnet', 'Getnet (TransAct)')],
        ondelete={'getnet': 'set default'},
    )
    getnet_url_webservice = fields.Char(
        string='URL del concentrador',
        default=getnet_utils.GETNET_URL_TESTING,
        help='URL base del Concentrador de Facturas TransAct. Testing: '
             '%s. La URL de producción la entrega New Age Data.'
             % getnet_utils.GETNET_URL_TESTING,
    )
    getnet_emp_cod = fields.Char(
        string='EmpCod',
        size=6,
        help='Código de empresa TransAct (largo 6), asignado por New Age '
             'Data. Ej: NEWAGE.',
    )
    getnet_emp_hash = fields.Char(
        string='EmpHash',
        groups='base.group_system',
        help='Hash de seguridad por razón social (llave privada). El de '
             'integración SIEMPRE difiere del de producción.',
    )
    getnet_is_multiple = fields.Boolean(
        string='Múltiples terminales',
        help='Marcar cuando el proveedor opera más de un POS: el pago '
             'deberá elegir a qué terminal (TermCod) enrutar el cobro.',
    )
    getnet_terminal_ids = fields.One2many(
        comodel_name='getnet.pos.terminal',
        inverse_name='payment_provider_id',
        string='Terminales Getnet',
    )
    getnet_modo_emulacion = fields.Boolean(
        string='Modo emulación',
        help='Setea Configuracion.ModoEmulacion=True en los posteos: '
             'TransAct emula el POS y responde aprobado con datos fijos. '
             'Solo para desarrollo, nunca en producción.',
    )

    # ------------------------------------------------------------------
    # Payload base y validaciones
    # ------------------------------------------------------------------
    def _getnet_check_credentials(self):
        self.ensure_one()
        faltantes = []
        if not self.getnet_url_webservice:
            faltantes.append('URL del concentrador')
        if not self.getnet_emp_cod:
            faltantes.append('EmpCod')
        if not self.sudo().getnet_emp_hash:
            faltantes.append('EmpHash')
        if faltantes:
            raise UserError(_(
                'Faltan credenciales TransAct en el proveedor %(provider)s: '
                '%(fields)s.',
                provider=self.name, fields=', '.join(faltantes),
            ))

    def _getnet_base_transaccion_vals(self, terminal):
        """
        Propiedades de identificación comunes a toda operación
        (manual WS: EmpHASH + EmpCod + TermCod).
        """
        self.ensure_one()
        self._getnet_check_credentials()
        if not terminal or not terminal.term_cod:
            raise UserError(_(
                'No hay terminal Getnet (TermCod) seleccionada para el '
                'proveedor %s.', self.name))
        return {
            'EmpHASH': self.sudo().getnet_emp_hash,
            'EmpCod': self.getnet_emp_cod,
            'TermCod': terminal.term_cod,
        }

    def _getnet_moneda_iso(self, currency):
        """MonedaISO del pago; rechaza monedas no soportadas (nunca asumir pesos)."""
        try:
            return getnet_utils.getnet_moneda_iso(currency.name)
        except ValueError:
            raise UserError(_(
                'TransAct/Getnet solo opera en Pesos (UYU) o Dólares (USD). '
                'La moneda %s no está soportada.', currency.name))

    # ------------------------------------------------------------------
    # Capa SOAP (el provider es el driver del motor de polling)
    # ------------------------------------------------------------------
    def _getnet_soap_transaccion(self, method, params):
        """
        Invoca un método del servicio de Transacciones. Devuelve
        (data, request_xml, response_xml); nunca lanza por transporte.
        """
        self.ensure_one()
        return getnet_utils.getnet_soap_call(
            self.getnet_url_webservice,
            getnet_utils.GETNET_TRANSACCION_SVC_PATH,
            getnet_utils.GETNET_TRANSACCION_CONTRACT,
            method,
            params,
        )

    def _getnet_soap_cierre(self, method, params):
        """Invoca un método del servicio de Cierres de Lote."""
        self.ensure_one()
        return getnet_utils.getnet_soap_call(
            self.getnet_url_webservice,
            getnet_utils.GETNET_CIERRE_SVC_PATH,
            getnet_utils.GETNET_CIERRE_CONTRACT,
            method,
            params,
        )

    # ------------------------------------------------------------------
    # Posteo
    # ------------------------------------------------------------------
    def getnet_postear_transaccion(self, transaccion_vals):
        """
        PostearTransaccion con manejo del código 9 (HAY_FACTURA_PENDIENTE).

        El token pendiente puede pertenecer a una transacción NUESTRA cuyo
        worker murió (takeover de lock huérfano, restart de Odoo): antes de
        cancelar se busca el token en payment.transaction y, si es propio,
        se CONSULTA para resolverlo — cancelarlo a ciegas perdería el rastro
        de un cobro ya aprobado en el pinpad. Solo se cancela un token
        propio si sigue genuinamente sin finalizar; los ajenos mantienen el
        comportamiento de cancelar sin pisar (y no repostear si el cancel
        falla).

        PRECONDICIÓN: el llamador ya tomó el lock de la terminal
        (getnet.pos.terminal.getnet_claim) y lo commiteó.

        :return: (data, request_xml, response_xml) del posteo definitivo.
        """
        self.ensure_one()
        data, req, resp = self._getnet_soap_transaccion(
            'PostearTransaccion', {'Transaccion': transaccion_vals})
        rc = getnet_utils.getnet_rc(data)
        if rc == getnet_utils.GETNET_RC_FACTURA_PENDIENTE:
            token_pendiente = data.get('TokenNro')
            if not token_pendiente:
                return data, req, resp
            huerfana = self.env['payment.transaction'].search([
                ('getnet_token', '=', token_pendiente),
                ('provider_id', '=', self.id),
            ], limit=1)
            if huerfana:
                _logger.warning(
                    'Getnet: factura pendiente (token %s) pertenece a la '
                    'transacción propia %s; se consulta antes de cancelar.',
                    token_pendiente, huerfana.reference)
                if not self._getnet_resolver_token_propio(huerfana):
                    # No se pudo resolver ni cancelar: no pisamos nada.
                    return data, req, resp
            else:
                _logger.warning(
                    'Getnet: terminal con factura pendiente ajena (token '
                    '%s); se cancela y se reintenta el posteo.',
                    token_pendiente)
                cancel_data, _creq, _cresp = self._getnet_soap_transaccion(
                    'CancelarTransaccion', {'TokenNro': token_pendiente})
                if getnet_utils.getnet_rc(cancel_data) != getnet_utils.GETNET_RC_OK:
                    # No se pudo cancelar (p.ej. ya confirmada): no pisamos
                    # esa transacción, devolvemos el error original.
                    return data, req, resp
            data, req, resp = self._getnet_soap_transaccion(
                'PostearTransaccion', {'Transaccion': transaccion_vals})
        return data, req, resp

    def _getnet_resolver_token_propio(self, tx):
        """
        Resuelve una transacción propia cuyo token quedó pendiente en la
        terminal (worker muerto): consulta el estado real y persiste.

        - Si ya finalizó (aprobada/denegada/cancelada): se persisten
          ticket/lote/autorización y estado — la consulta misma confirma la
          transacción ante TransAct y limpia el pendiente.
        - Si sigue genuinamente sin finalizar: se cancela; con cancel OK se
          hace una consulta más para persistir el estado CANCELADA
          consistente.

        :return: True si la terminal quedó libre para repostear.
        """
        self.ensure_one()
        data, req, resp = self._getnet_soap_transaccion(
            'ConsultarTransaccion', {'TokenNro': tx.getnet_token})
        estado = getnet_utils.getnet_estado_avance(data)
        if (getnet_utils.getnet_finalizado(data)
                or estado in getnet_utils.ESTADOS_FINALES):
            tx.getnet_persist_query_result({
                'data': data, 'request_xml': req, 'response_xml': resp,
                'timeout': False,
            })
            _logger.info(
                'Getnet: transacción huérfana %s resuelta por consulta '
                '(estado %s).', tx.reference, tx.state)
            return True
        cancel_data, _creq, _cresp = self._getnet_soap_transaccion(
            'CancelarTransaccion', {'TokenNro': tx.getnet_token})
        if getnet_utils.getnet_rc(cancel_data) != getnet_utils.GETNET_RC_OK:
            _logger.warning(
                'Getnet: no se pudo cancelar el token propio pendiente %s '
                '(%s); no se repostea.', tx.getnet_token,
                cancel_data.get('Resp_MensajeError'))
            return False
        data2, req2, resp2 = self._getnet_soap_transaccion(
            'ConsultarTransaccion', {'TokenNro': tx.getnet_token})
        estado2 = getnet_utils.getnet_estado_avance(data2)
        if (getnet_utils.getnet_finalizado(data2)
                or estado2 in getnet_utils.ESTADOS_FINALES):
            tx.getnet_persist_query_result({
                'data': data2, 'request_xml': req2, 'response_xml': resp2,
                'timeout': False,
            })
        else:
            tx._set_canceled(state_message=_(
                'Getnet: cancelada al recuperar la terminal (token '
                'pendiente de un worker interrumpido).'))
        return True

    def getnet_postear_transaccion_con_lock(self, terminal, transaccion_vals,
                                            origin, ref='', tx=None,
                                            start_worker=None):
        """
        Orquestación claim -> commit -> posteo -> arranque del worker, con
        liberación garantizada del lock en TODO camino de error.

        El claim se commitea para hacerse visible a otros workers ANTES de
        tocar el WS; a partir de ahí un rollback de Odoo ya no lo deshace,
        por lo que cualquier fallo entre el claim y el arranque efectivo
        del polling (excepción de red, posteo con RC != 0, error al lanzar
        el hilo) debe liberar el lock explícitamente y commitear esa
        liberación — si no, cada fallo transitorio deja la terminal tomada
        por el TTL completo.

        ``tx`` (payment.transaction, opcional): con posteo OK se le
        persiste el token y la terminal — imprescindible para que el cron
        de recuperación pueda resolverla si el resto del arranque falla.

        ``start_worker`` (callable(data), opcional): lanza el hilo de
        polling DENTRO del try. Si su lanzamiento explota, se libera el
        lock y la transacción queda 'pending' con su token (el cron la
        resuelve); nunca queda una terminal tomada hasta el rescate por
        heartbeat por un fallo de arranque.

        Con posteo OK y worker arrancado, el lock QUEDA tomado: pasa a ser
        responsabilidad del finally del worker liberarlo.

        :return: (data, request_xml, response_xml) del posteo.
        """
        self.ensure_one()
        terminal.getnet_claim(origin, ref)
        getnet_utils.getnet_safe_commit(self.env)
        try:
            data, req, resp = self.getnet_postear_transaccion(transaccion_vals)
        except Exception:
            terminal.getnet_release()
            getnet_utils.getnet_safe_commit(self.env)
            raise
        if getnet_utils.getnet_rc(data) != getnet_utils.GETNET_RC_OK:
            # El polling no va a arrancar: la terminal debe quedar libre ya.
            terminal.getnet_release()
            getnet_utils.getnet_safe_commit(self.env)
            return data, req, resp
        token = data.get('TokenNro')
        if tx is not None and token:
            tx.write({
                'getnet_token': token,
                'getnet_terminal_id': terminal.id,
            })
            getnet_utils.getnet_safe_commit(self.env)
        if start_worker is not None:
            try:
                start_worker(data)
            except Exception:
                # Último tramo sin dueño explícito entre el claim y el
                # finally del worker: liberar y delegar la resolución de la
                # transacción (token ya persistido) al cron de recuperación.
                terminal.getnet_release()
                if tx is not None:
                    tx._set_pending(state_message=_(
                        'Getnet: falló el arranque del worker de polling; '
                        'la transacción será resuelta por el cron de '
                        'recuperación (token %s).', token))
                getnet_utils.getnet_safe_commit(self.env)
                raise
        return data, req, resp
