# -*- coding: utf-8 -*-
"""Cada llamada a OCA (POSLink), con lo que se mandó y lo que contestó.

La transacción guardaba sólo los datos del cobro (`oca_complete_request`) y la respuesta
final. No quedaba qué se le mandó a OCA en cada paso —la compra, las consultas mientras el
cliente pasa la tarjeta, la confirmación, el reverso, la anulación— ni nada de un cobro que
falló antes de crear la transacción.

* El registro se escribe en un cursor propio: un error que deshace la transacción del cobro
  no se lleva lo que se mandó.
* Se vincula a la transacción por PosID + TransactionId, que viajan en cada llamada; así no
  depende de cuándo se crea la transacción.
* Las consultas se repiten cada pocos segundos mientras el pinpad espera: una respuesta igual
  a la anterior de la misma operación no crea otra fila, suma una repetición.
"""
import json
import logging
import threading
import time
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DIAS_POR_DEFECTO = 90


def _texto(valor):
    if valor in (None, '', {}, []):
        return False
    if isinstance(valor, str):
        try:
            return json.dumps(json.loads(valor), indent=2, ensure_ascii=False)
        except ValueError:
            return valor
    try:
        return json.dumps(valor, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(valor)


def _dato(*fuentes, claves=()):
    for fuente in fuentes:
        if not isinstance(fuente, dict):
            continue
        for clave in claves:
            valor = fuente.get(clave)
            if valor not in (None, '', 0, '0'):
                return str(valor)
    return False


def oca_post(env, post, endpoint, json=None, headers=None, timeout=30, **kwargs):
    """`post(endpoint, json=..., headers=..., timeout=...)` registrado en `oca.envio`.

    `post` es el `requests.post` del módulo que llama (así lo que los tests reemplazan en ese
    módulo se sigue usando). Devuelve la respuesta tal cual y propaga las excepciones."""
    t0 = time.time()
    try:
        respuesta = post(endpoint, json=json, headers=headers, timeout=timeout, **kwargs)
    except Exception as error:
        env['oca.envio']._registrar(endpoint, json, error=str(error),
                                    duracion_ms=int((time.time() - t0) * 1000))
        raise
    env['oca.envio']._registrar(endpoint, json, respuesta=respuesta,
                                duracion_ms=int((time.time() - t0) * 1000))
    return respuesta


class OcaEnvio(models.Model):
    _name = 'oca.envio'
    _description = 'Llamada a OCA (POSLink)'
    _order = 'id desc'
    _rec_name = 'operacion'

    fecha = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    fecha_ultima = fields.Datetime(string="Última repetición", readonly=True)
    repeticiones = fields.Integer(default=1, readonly=True,
                                  help="Veces que se hizo la misma llamada con la misma respuesta.")
    operacion = fields.Char(string="Operación", readonly=True, index=True)
    url = fields.Char(string="Dirección", readonly=True)
    request = fields.Text(string="Enviado", readonly=True)
    status_http = fields.Integer(string="HTTP", readonly=True)
    respuesta = fields.Text(readonly=True)
    response_code = fields.Char(string="ResponseCode", readonly=True)
    mensaje = fields.Text(readonly=True)
    resultado = fields.Selection([
        ('exito', 'Respondió'),
        ('rechazado', 'Error HTTP'),
        ('error', 'Sin respuesta'),
    ], readonly=True, index=True)
    error = fields.Text(readonly=True)
    duracion_ms = fields.Integer(string="Duración (ms)", readonly=True)
    pos_id = fields.Char(string="PosID", readonly=True, index=True)
    oca_transaction_id = fields.Char(string="TransactionId", readonly=True, index=True)
    usuario_id = fields.Many2one('res.users', string="Usuario", readonly=True, ondelete='set null')

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------
    @api.model
    def _registrar(self, endpoint, data, respuesta=None, error=None, duracion_ms=0):
        """Nunca lanza: si no se puede registrar, el cobro sigue igual."""
        try:
            vals = self._valores(endpoint, data, respuesta, error, duracion_ms)
            if getattr(threading.current_thread(), 'testing', False):
                with self.env.cr.savepoint():
                    self.sudo()._guardar(vals)
                return
            with self.env.registry.cursor() as cr:
                self.env(cr=cr, su=True)['oca.envio']._guardar(vals)
        except Exception as e:
            _logger.warning("OCA: no se pudo registrar la llamada a %s: %s", endpoint, e)

    @api.model
    def _valores(self, endpoint, data, respuesta, error, duracion_ms):
        status, texto, datos = 0, None, None
        if respuesta is not None:
            status = respuesta.status_code if isinstance(respuesta.status_code, int) else 0
            texto = respuesta.text if isinstance(getattr(respuesta, 'text', None), str) else None
            try:
                datos = json.loads(texto) if texto else None
            except ValueError:
                datos = None
        if error:
            resultado = 'error'
        else:
            resultado = 'exito' if 200 <= status < 300 else 'rechazado'
        return {
            'operacion': (endpoint or '').rstrip('/').rsplit('/', 1)[-1] or False,
            'url': endpoint or False,
            'request': _texto(data),
            'status_http': status,
            'respuesta': _texto(texto),
            'response_code': _dato(datos, claves=('ResponseCode',)) or (
                '0' if isinstance(datos, dict) and str(datos.get('ResponseCode')) == '0' else False),
            'mensaje': _dato(datos, claves=('msg', 'Message', 'ResponseMessage')),
            'resultado': resultado,
            'error': error or False,
            'duracion_ms': duracion_ms,
            'pos_id': _dato(data, datos, claves=('PosID', 'PosId')),
            'oca_transaction_id': _dato(data, datos, claves=('TransactionId', 'STransactionId')),
            'usuario_id': self.env.uid,
        }

    @api.model
    def _guardar(self, vals):
        """Una consulta igual a la anterior de la misma operación suma una repetición."""
        if vals['oca_transaction_id'] and vals['resultado'] == 'exito':
            anterior = self.search([
                ('operacion', '=', vals['operacion']),
                ('pos_id', '=', vals['pos_id']),
                ('oca_transaction_id', '=', vals['oca_transaction_id']),
            ], limit=1)
            # Sólo la respuesta: la consulta lleva la hora en el pedido y cambia cada vez.
            if anterior and anterior.respuesta == vals['respuesta']:
                anterior.write({'repeticiones': anterior.repeticiones + 1,
                                'fecha_ultima': fields.Datetime.now()})
                return anterior
        return self.create(vals)

    @api.model
    def _cron_limpiar(self):
        dias = self.env['ir.config_parameter'].sudo().get_param('odoo_pos_oca.envio_dias', DIAS_POR_DEFECTO)
        try:
            dias = int(dias)
        except (TypeError, ValueError):
            dias = DIAS_POR_DEFECTO
        if dias <= 0:
            return True
        self.sudo().search([('fecha', '<', fields.Datetime.now() - timedelta(days=dias))]).unlink()
        return True


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    oca_envio_ids = fields.Many2many('oca.envio', string="Llamadas a OCA",
                                     compute='_compute_oca_envio_ids')

    @api.depends('oca_transaction_id', 'pos_id')
    def _compute_oca_envio_ids(self):
        Envio = self.env['oca.envio'].sudo()
        for tx in self:
            if tx.oca_transaction_id and tx.oca_transaction_id != '0':
                dominio = [('oca_transaction_id', '=', tx.oca_transaction_id)]
                if tx.pos_id:
                    dominio.append(('pos_id', '=', tx.pos_id))
                tx.oca_envio_ids = Envio.search(dominio, order='id')
            else:
                tx.oca_envio_ids = False