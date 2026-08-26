# -*- coding: utf-8 -*-
"""
Cierre de lote TransAct (obs. 6 del plan).

Patrón del manual WS: los lotes se persisten en Abierto con el Lote que
devuelve cada transacción aprobada, y al cierre se impactan como Cerrados
con los totales de venta/anulación/devolución. El cierre REVERSA las
transacciones pendientes de confirmación, por eso postearlo exige que no
haya transacciones en vuelo en la terminal (bloqueante; forzar es una
acción separada con rastro).

Estructura real (WSDL TarjetasCierre_400, validado 17/8/2026):
  PostearCierre(Cierre) / PostearConsultaUltimoCierre(ConsultaUltimoCierre)
  -> RespuestaPostearCierre { Resp_CodigoRespuesta, TokenNro, ... }
  ConsultarCierre(TokenNro) -> RespuestaConsultarCierre {
      Resp_CierreFinalizado, Estado, Voucher[],
      DatosCierre: [ IDatosCierre {
          Aprobado, CodRespuesta, MsgRespuesta, NroAutorizacion, Lote,
          ProcesadorId,
          Extendida { CantVenta, MontoVenta, CantDevolucion,
                      MontoDevolucion, CantAnulacion, MontoAnulacion,
                      CierreFechaHora, Productos[...] } } ] }

DatosCierre es un ARRAY (uno por procesador) y los nombres de totales se
repiten varios niveles más abajo (Productos > Monedas > Planes >
Nacionales/Extranjeras > Venta/Devolucion/Anulacion), por lo que los
totales se leen del árbol y NUNCA del dict aplanado.

Queda pendiente de homologación (no del WSDL) el texto exacto del mensaje
"no hay cierres pendientes" que dispara el fallback a
PostearConsultaUltimoCierre.
"""

import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import getnet_utils

_logger = logging.getLogger(__name__)

CIERRE_TIMEOUT = 180
CIERRE_WAIT_DEFAULT = 5


class GetnetLoteCierre(models.Model):
    _name = 'getnet.lote.cierre'
    _description = 'Lote de tarjetas Getnet (TransAct)'
    _order = 'id desc'

    terminal_id = fields.Many2one(
        'getnet.pos.terminal', string='Terminal', required=True,
        ondelete='restrict', index=True)
    provider_id = fields.Many2one(
        'payment.provider', string='Proveedor', required=True,
        ondelete='restrict')
    lote = fields.Char(string='Lote', index=True)
    state = fields.Selection(
        [('abierto', 'Abierto'), ('cerrado', 'Cerrado')],
        string='Estado', default='abierto', required=True, copy=False)
    token_cierre = fields.Char(string='Token de cierre', copy=False)
    aprobado = fields.Boolean(string='Cierre aprobado', copy=False)
    fecha_cierre = fields.Datetime(string='Fecha de cierre', copy=False)
    cant_venta = fields.Integer(string='Cant. ventas', copy=False)
    monto_venta = fields.Float(string='Monto ventas', copy=False)
    cant_anulacion = fields.Integer(string='Cant. anulaciones', copy=False)
    monto_anulacion = fields.Float(string='Monto anulaciones', copy=False)
    cant_devolucion = fields.Integer(string='Cant. devoluciones', copy=False)
    monto_devolucion = fields.Float(string='Monto devoluciones', copy=False)
    respuesta_cruda = fields.Text(string='Respuesta completa', copy=False)

    @api.model
    def getnet_upsert_lote_abierto(self, terminal, provider, lote):
        """Crea (si no existe) el lote en Abierto para la terminal."""
        if not lote:
            return self.browse()
        existente = self.search([
            ('terminal_id', '=', terminal.id), ('lote', '=', str(lote)),
            ('state', '=', 'abierto')], limit=1)
        return existente or self.create({
            'terminal_id': terminal.id, 'provider_id': provider.id,
            'lote': str(lote)})


class GetnetPosTerminalCierre(models.Model):
    _inherit = 'getnet.pos.terminal'

    def _getnet_txs_en_vuelo(self):
        """Transacciones en vuelo de la terminal (backend, POS o cron)."""
        self.ensure_one()
        return self.env['payment.transaction'].search([
            ('getnet_terminal_id', '=', self.id),
            ('state', 'in', ('draft', 'pending')),
            ('getnet_token', '!=', False)])

    def action_getnet_cerrar_lote(self):
        self.ensure_one()
        return self.getnet_cerrar_lote(force=False)

    def action_getnet_forzar_cierre_lote(self):
        """
        Cierre forzado: el cierre REVERSA transacciones pendientes de
        confirmación — solo administrador y con rastro en el log.
        """
        self.ensure_one()
        _logger.warning(
            'Getnet: cierre de lote FORZADO en la terminal %s por el '
            'usuario %s (id %s) con %s transacciones en vuelo.',
            self.display_name, self.env.user.name, self.env.uid,
            len(self._getnet_txs_en_vuelo()))
        return self.getnet_cerrar_lote(force=True)

    def getnet_cerrar_lote(self, force=False):
        """PostearCierre(ProcesadorId=0) -> poll -> persistir totales."""
        self.ensure_one()
        provider = self.payment_provider_id
        en_vuelo = self._getnet_txs_en_vuelo()
        if en_vuelo and not force:
            raise UserError(_(
                'No se puede cerrar el lote: la terminal %(term)s tiene '
                '%(cant)s transacción(es) en vuelo (%(refs)s). El cierre '
                'reversaría las pendientes de confirmación. Espere a que '
                'se resuelvan (o use el cierre forzado, acción de '
                'administrador).',
                term=self.display_name, cant=len(en_vuelo),
                refs=', '.join(en_vuelo.mapped('reference')[:5])))
        cierre_vals = provider._getnet_base_transaccion_vals(self)
        cierre_vals['ProcesadorId'] = 0
        cierre_vals['CierreCentralizado'] = False
        if provider.getnet_modo_emulacion:
            cierre_vals['Configuracion'] = {'ModoEmulacion': True}
        self.getnet_claim('cierre_lote', ref='CIERRE')
        getnet_utils.getnet_safe_commit(self.env)
        try:
            # El contrato envuelve el Cierre en un parámetro con nombre
            # propio por método (Cierre / ConsultaUltimoCierre).
            data, req, resp = provider._getnet_soap_cierre(
                'PostearCierre', {'Cierre': cierre_vals})
            rc = getnet_utils.getnet_rc(data)
            msg = (data.get('Resp_MensajeError') or '').upper()
            # Texto pendiente de homologación (no está en el WSDL).
            if rc != getnet_utils.GETNET_RC_OK and 'NO HAY CIERRES' in msg:
                # Recuperar los totales del último cierre (timeout previo)
                data, req, resp = provider._getnet_soap_cierre(
                    'PostearConsultaUltimoCierre',
                    {'ConsultaUltimoCierre': cierre_vals})
                rc = getnet_utils.getnet_rc(data)
            if rc != getnet_utils.GETNET_RC_OK:
                raise UserError(_(
                    'TransAct rechazó el cierre de lote (%(rc)s): %(msg)s',
                    rc=rc, msg=data.get('Resp_MensajeError') or ''))
            token = data.get('TokenNro')
            data_final, arbol_final = self._getnet_poll_cierre(
                provider, token, data)
            # Finalizado != exitoso: contra el concentrador de testing un
            # cierre sin POS que lo levante termina con
            # Resp_CierreFinalizado=true, ESTADOAVANCE_FINALIZADA_ERROR,
            # Estado='EXPIRADA(POS NO BUSCO TRANSACCION)' y DatosCierre
            # vacío. Marcar los lotes como cerrados en ese caso sería
            # perder el lote sin haberlo cerrado en la terminal.
            estado = getnet_utils.getnet_estado_avance(data_final)
            datos = self._getnet_datos_cierre(arbol_final)
            if (estado != getnet_utils.ESTADOAVANCE_FINALIZADA_CORRECTAMENTE
                    or not datos):
                raise UserError(_(
                    'El cierre de lote no se completó en la terminal '
                    '%(term)s (estado TransAct: %(estado)s). No se cerró '
                    'ningún lote.',
                    term=self.display_name,
                    estado=(data_final.get('Estado')
                            or data_final.get('Resp_EstadoAvance') or '')))
            self._getnet_persistir_cierre(provider, token, arbol_final)
            return True
        finally:
            self.getnet_release()
            getnet_utils.getnet_safe_commit(self.env)

    def _getnet_poll_cierre(self, provider, token, post_data):
        """
        ConsultarCierre hasta finalización; ante timeout, reintenta la
        consulta (los cierres no tienen reverso — manual WS).

        Devuelve (data_aplanado, árbol) de la última consulta: los totales
        viven en DatosCierre[*].Extendida y sus nombres se repiten en los
        subniveles por producto/plan, así que se leen del árbol.
        """
        start = time.monotonic()
        wait = getnet_utils.getnet_segundos_reconsulta(
            post_data, CIERRE_WAIT_DEFAULT)
        while True:
            time.sleep(min(max(wait, 1), 15))
            self.getnet_touch()
            data, _req, resp = provider._getnet_soap_cierre(
                'ConsultarCierre', {'TokenNro': token})
            # Nombre confirmado por el WSDL: Resp_CierreFinalizado.
            if getnet_utils.getnet_finalizado(data):
                return data, getnet_utils.getnet_parse_soap_tree(
                    (resp or '').encode('utf-8'))
            if time.monotonic() - start >= CIERRE_TIMEOUT:
                raise UserError(_(
                    'El cierre de lote no respondió a tiempo (token %s). '
                    'Reintente: si TransAct responde "no hay cierres '
                    'pendientes", se recuperarán los totales del último '
                    'cierre.', token))
            wait = getnet_utils.getnet_segundos_reconsulta(
                data, CIERRE_WAIT_DEFAULT)

    @api.model
    def _getnet_datos_cierre(self, arbol):
        """
        Extrae la lista de IDatosCierre del árbol de RespuestaConsultarCierre.

        Hay un IDatosCierre por procesador; el wrapper ArrayOf... aparece
        como dict con un item o como lista con varios.
        """
        resultado = arbol
        for clave in ('ConsultarCierreResponse', 'ConsultarCierreResult'):
            if isinstance(resultado, dict) and clave in resultado:
                resultado = resultado[clave]
        if not isinstance(resultado, dict):
            return []
        return [d for d in getnet_utils.getnet_array_items(
            resultado.get('DatosCierre')) if isinstance(d, dict)]

    def _getnet_persistir_cierre(self, provider, token, arbol):
        """Impacta los lotes Abiertos como Cerrados con los totales."""
        self.ensure_one()
        datos = self._getnet_datos_cierre(arbol)

        def _num(clave, cast):
            """Suma el total ``clave`` de todos los procesadores del cierre.

            Se lee SOLO de DatosCierre[i].Extendida: el mismo nombre existe
            en los subtotales por plan/decreto y sumarlos duplicaría.
            """
            total = 0
            for item in datos:
                extendida = item.get('Extendida')
                if not isinstance(extendida, dict):
                    continue
                valor = extendida.get(clave)
                if isinstance(valor, (dict, list)):
                    continue
                try:
                    total += cast(valor or 0)
                except (TypeError, ValueError):
                    continue
            return total

        aprobado = bool(datos) and all(
            str(item.get('Aprobado') or '').strip().lower() == 'true'
            for item in datos)
        lotes = [str(item.get('Lote') or '') for item in datos
                 if item.get('Lote')]
        vals = {
            'state': 'cerrado',
            'token_cierre': token or '',
            'aprobado': aprobado,
            'fecha_cierre': fields.Datetime.now(),
            'cant_venta': _num('CantVenta', int),
            'monto_venta': _num('MontoVenta', float) / 100.0,
            'cant_anulacion': _num('CantAnulacion', int),
            'monto_anulacion': _num('MontoAnulacion', float) / 100.0,
            'cant_devolucion': _num('CantDevolucion', int),
            'monto_devolucion': _num('MontoDevolucion', float) / 100.0,
            'respuesta_cruda': str(arbol),
        }
        abiertos = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.id), ('state', '=', 'abierto')])
        if abiertos:
            abiertos.write(vals)
        else:
            vals.update({'terminal_id': self.id,
                         'provider_id': provider.id,
                         'lote': lotes[0] if lotes else ''})
            self.env['getnet.lote.cierre'].create(vals)
