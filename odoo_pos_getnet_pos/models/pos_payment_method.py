# -*- coding: utf-8 -*-
"""
Método de pago POS con terminal Getnet/TransAct.

El posteo y el polling viven en el SERVER (mismo wrapper con lock y motor
del core — el POS no bypasea el lock por terminal): el JS solo dispara el
RPC y espera la resolución por bus (GETNET_LATEST_RESPONSE).
"""

import logging
import threading

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils

_logger = logging.getLogger(__name__)


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [
            ('getnet', 'Getnet TransAct')]

    getnet_provider_id = fields.Many2one(
        comodel_name='payment.provider',
        string='Proveedor Getnet',
        domain="[('code', '=', 'getnet')]",
        help='Credenciales TransAct (EmpHash/EmpCod/URL) resueltas siempre '
             'desde el proveedor.',
    )
    getnet_terminal_id = fields.Many2one(
        comodel_name='getnet.pos.terminal',
        string='Terminal Getnet (TermCod)',
    )

    def _getnet_terminal(self):
        self.ensure_one()
        if self.getnet_terminal_id:
            return self.getnet_terminal_id
        terminals = self.getnet_provider_id.getnet_terminal_ids
        if len(terminals) == 1:
            return terminals
        raise UserError(_(
            'Configure la terminal Getnet (TermCod) del método de pago %s.',
            self.name))

    def _get_pos_factura_nro(self, data):
        """
        FacturaNro del posteo en el flujo POS.

        Criterio definitivo (New Age Data, 17/8/2026): el cobro opera
        desde el pago, con o sin factura. En el TPV se cobra ANTES de
        emitir el CFE, así que no hay número de factura real.

        Se manda 0 y se omiten los demás Factura*: omitir FacturaNro por
        completo NO sirve, el concentrador responde rc=2 'CAMPO REQUERIDO
        / VERIFIQUE / FACTURA' (probado contra el ambiente de integración
        el 17/8/2026).

        TODO-homologación: si en la homologación aparece que la devolución
        de IVA (ley 19210) al consumidor final exige los Factura*, habría
        que emitir el CFE antes del cobro o mandar los montos sin número.
        Este método sigue siendo el único punto a cambiar.
        """
        self.ensure_one()
        return getnet_utils.GETNET_FACTURA_NRO_SIN_FACTURA

    def _getnet_ticket_original_for_refund(self, data):
        """Ticket de la transacción aprobada de la orden reembolsada."""
        self.ensure_one()
        order_ids = data.get('refunded_order_ids') or []
        # sudo: payment.transaction solo tiene ACL para base.group_system
        # y quien opera esto es un cajero del TPV.
        tx = self.env['payment.transaction'].sudo().search([
            ('getnet_pos_order_id', 'in', order_ids),
            ('provider_id', '=', self.getnet_provider_id.id),
            ('state', '=', 'done'),
            ('getnet_ticket', '!=', False),
        ], order='id desc', limit=1)
        if not tx:
            raise UserError(_(
                'No se encontró una transacción Getnet aprobada de la '
                'orden original para emitir la devolución.'))
        # TicketOriginal es xs:int; el Ticket se persiste como texto de un
        # xs:double, así que se normaliza antes de reenviarlo.
        try:
            return getnet_utils.getnet_entero_contrato(
                tx.getnet_ticket, 'TicketOriginal')
        except ValueError:
            raise UserError(_(
                'La transacción original %s no tiene un número de ticket '
                'válido (%s); no se puede emitir la devolución.',
                tx.reference, tx.getnet_ticket))

    # ------------------------------------------------------------------
    # RPC desde el POS
    # ------------------------------------------------------------------
    def getnet_enviar_pago(self, data):
        """
        Postea el cobro/devolución de una línea de pago del TPV.

        :param data: dict del JS con amount, currency_id, session_id,
                     config_id, tracking_number, order_uid, is_refund,
                     refunded_order_ids.
        :return: dict {'rc', 'msg', 'token', 'tx_reference'}
        """
        self.ensure_one()
        provider = self.getnet_provider_id
        if not provider or provider.code != 'getnet':
            raise UserError(_(
                'El método de pago %s no tiene proveedor Getnet.', self.name))
        terminal = self._getnet_terminal()
        currency = self.env['res.currency'].browse(data['currency_id'])
        amount = abs(data['amount'])
        payload = provider._getnet_base_transaccion_vals(terminal)
        payload['MonedaISO'] = provider._getnet_moneda_iso(currency)
        payload['Monto'] = getnet_utils.getnet_centavos(amount)
        if data.get('is_refund'):
            payload['Operacion'] = getnet_utils.GETNET_OPERACION_DEVOLUCION
            payload['TicketOriginal'] = \
                self._getnet_ticket_original_for_refund(data)
        else:
            payload['Operacion'] = getnet_utils.GETNET_OPERACION_VENTA
            # None => el builder omite el elemento (ver _get_pos_factura_nro)
            factura_nro = self._get_pos_factura_nro(data)
            if factura_nro is not None:
                payload['FacturaNro'] = factura_nro
        if provider.getnet_modo_emulacion:
            payload['Configuracion'] = {'ModoEmulacion': True}
        # DecretoLeyId sin setear: lo solicita el POS al cajero (manual).

        method = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        # sudo: el cajero no tiene derechos sobre payment.transaction (ACL
        # del core: solo base.group_system). La transacción la crea la
        # máquina en su nombre.
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': method.id,
            'reference': 'GETNET-POS-%s-%s' % (
                data.get('order_uid') or self.id,
                fields.Datetime.now().strftime('%Y%m%d%H%M%S')),
            'amount': amount,
            'currency_id': currency.id,
            # El TPV puede cobrar sin cliente: fallback al partner de la
            # compañía (payment.transaction exige partner_id al crear)
            'partner_id': data.get('partner_id')
                          or self.env.company.partner_id.id,
            'getnet_transaction_origin': 'pos_payment',
            'getnet_terminal_id': terminal.id,
        })
        session = self.env['pos.session'].browse(data['session_id'])
        if not session.exists():
            raise UserError(_('La sesión POS indicada no existe.'))
        channel = session._get_bus_channel_name()
        config_id = session.config_id.id
        try:
            resp_data, _req, _resp = provider.getnet_postear_transaccion_con_lock(
                terminal, payload, 'pos', ref=tx.reference, tx=tx,
                start_worker=lambda d: self._getnet_start_pos_worker(
                    tx, terminal, provider, d, channel, config_id))
        except UserError:
            raise
        rc = getnet_utils.getnet_rc(resp_data)
        if rc != getnet_utils.GETNET_RC_OK:
            tx._set_error(_(
                'Getnet POS: posteo rechazado (%(rc)s) %(msg)s',
                rc=rc, msg=resp_data.get('Resp_MensajeError') or ''))
            getnet_utils.getnet_safe_commit(self.env)
        return {
            'rc': rc,
            'msg': resp_data.get('Resp_MensajeError') or '',
            'token': resp_data.get('TokenNro') or '',
            'tx_reference': tx.reference,
        }

    def getnet_cancelar(self, token):
        """CancelarTransaccion desde el botón de cancelar del TPV."""
        self.ensure_one()
        provider = self.getnet_provider_id
        data, _req, _resp = provider._getnet_soap_transaccion(
            'CancelarTransaccion', {'TokenNro': token})
        return {
            'rc': getnet_utils.getnet_rc(data),
            'msg': data.get('Resp_MensajeError') or '',
        }

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _getnet_start_pos_worker(self, tx, terminal, provider, post_data,
                                 channel, config_id):
        self.ensure_one()
        initial_wait = getnet_utils.getnet_segundos_reconsulta(post_data, 5)
        thread = threading.Thread(
            target=self._getnet_pos_worker_entry,
            args=(self.env.cr.dbname, self.env.uid, tx.id, terminal.id,
                  provider.id, initial_wait, channel, config_id),
            daemon=True,
        )
        thread.start()

    @api.model
    def _getnet_pos_worker_entry(self, dbname, uid, tx_id, terminal_id,
                                 provider_id, initial_wait, channel,
                                 config_id):
        import odoo
        registry = odoo.registry(dbname)
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, uid, {})
            # sudo: el hilo corre con el uid del operador y
            # payment.transaction solo tiene ACL de sistema.
            tx = env['payment.transaction'].sudo().browse(tx_id)
            terminal = env['getnet.pos.terminal'].browse(terminal_id)
            provider = env['payment.provider'].browse(provider_id)
            try:
                self.with_env(env)._getnet_pos_worker_inner(
                    tx, terminal, provider, initial_wait, channel, config_id)
            except Exception:
                _logger.exception(
                    'Getnet POS: fallo en worker de tx %s; la resolverá el '
                    'cron de recuperación.', tx_id)
            finally:
                terminal.getnet_release()
                getnet_utils.getnet_safe_commit(env)

    def _getnet_pos_worker_inner(self, tx, terminal, provider, initial_wait,
                                 channel, config_id):
        """Separado del manejo de cursor para poder testearlo sincrónico."""
        result = tx.getnet_run_query_loop(
            provider, tx.getnet_token, terminal=terminal,
            initial_wait=initial_wait)
        tx.getnet_persist_query_result(result)
        payload = {
            'id_config': config_id,
            'tx_reference': tx.reference,
            'approved': tx.state == 'done',
            'state': tx.state,
            'ticket': tx.getnet_ticket or '',
            'lote': tx.getnet_lote or '',
            'authorization': tx.getnet_nro_autorizacion or '',
            'card_type': tx.getnet_tarjeta_tipo or '',
            'msg': tx.getnet_msg_respuesta or '',
        }
        try:
            tx.env['bus.bus'].sudo()._sendone(
                channel, 'GETNET_LATEST_RESPONSE', payload)
        except Exception:
            _logger.exception('Getnet POS: error notificando por bus.')
        return payload
