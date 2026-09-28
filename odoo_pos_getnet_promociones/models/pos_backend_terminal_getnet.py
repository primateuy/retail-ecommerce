# -*- coding: utf-8 -*-
"""
Promociones por tarjeta sobre la terminal Getnet del POS Backend.

Usa las operaciones opcionales 8 del contrato de terminales (preparar el
cobro, opciones del medio, avisos del pedido), así que el POS no sabe que
existen las promociones. Por medio de pago se elige el modo:

- **auto (B)**: antes de cobrar se LEE la tarjeta en el pinpad
  (PostearConsultaDatosTarjeta / ConsultarDatosTarjeta), se busca la
  promoción por sello, emisor, tipo y BIN, se aplica, y el cobro se postea por
  el importe reducido y RESTRINGIDO a esa misma tarjeta (TarjetaId, EmisorId,
  TarjetaTipo). Si la lectura falla por cualquier motivo, esa venta pasa sola
  a manual con un aviso: la lectura NUNCA traba el cobro.
- **manual (A)**: el cajero elige «Getnet · <promo>»; el cobro se postea
  restringido a lo que pide la promoción.
- **off**: nada de esto.

Y en todos los modos con promociones, cada cobro APROBADO se compara con el
catálogo: la tarjeta que pagó puede no coincidir con la promoción aplicada
(PROMO NO COINCIDE, bloquea) o calificar para una que no se aplicó (PROMO NO
APLICADA). Nunca se aplica ni se quita sola una promoción sobre un cobro
aprobado: decide el cajero, y queda registrado en el pedido.
"""

import json
import logging
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils

from . import getnet_supuestos_lectura as supuestos

_logger = logging.getLogger(__name__)

AVISO = 'getnet_promo'


def _sanear_xml(xml):
    """La respuesta cruda sin número de tarjeta, titular ni credenciales."""
    for campo in supuestos.CAMPOS_SENSIBLES:
        xml = re.sub(r'(<(?:\w+:)?%s[^>]*>)[^<]*(</)' % campo, r'\1***\2', xml or '')
    return xml


def _sanear_datos(data):
    return {k: v for k, v in (data or {}).items() if k not in supuestos.CAMPOS_SENSIBLES}


class PosBackendTerminalGetnet(models.AbstractModel):
    _inherit = 'pos_backend.terminal.getnet'

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _promo_activo(self, payment_method):
        return (payment_method.terminal_provider == 'getnet'
                and (payment_method.getnet_modo_promociones or 'off') != 'off')

    def _promo_hay_catalogo(self, order):
        return bool(self.env['getnet.promocion']._vigentes(order.company_id))

    def _promo_moneda_ok(self, payment_method, order):
        """El catálogo es en la moneda de la empresa; otra moneda, sin promo."""
        moneda_medio = payment_method.currency_id or order.company_id.currency_id
        return moneda_medio == (order.currency_id or order.company_id.currency_id)

    def _promo_pasar_a_manual(self, order, motivo, lectura=None):
        """Fallback B -> A. La venta sigue: el próximo Agregar cobra directo."""
        if lectura:
            lectura.sudo().write({'state': 'fallida', 'motivo': motivo[:250]})
        order.sudo().getnet_promocion_manual = True
        order._getnet_registrar('pasa_a_manual', detalle=motivo[:250])
        _logger.warning('Getnet promociones: %s pasa a selección manual: %s',
                        order.name, motivo)
        return {
            'state': 'fallback',
            'level': 'warning',
            'message': _(
                'No se pudo leer la tarjeta para las promociones (%s). Esta '
                'venta pasa a promociones manuales: si la tarjeta tiene '
                'promoción, elegila en «Getnet · …»; si no, tocá Agregar de '
                'nuevo y se cobra el total.', motivo),
        }

    def _promo_tarjeta_de_datos(self, data):
        return {
            'tarjeta_id': str(data.get('TarjetaId') or ''),
            'emisor_id': str(data.get('EmisorId') or ''),
            'tarjeta_tipo': str(data.get('TarjetaTipo') or ''),
            'iin': str(data.get('TarjetaIIN') or ''),
        }

    # ------------------------------------------------------------------
    # 8a · Preparar el cobro: la lectura de la tarjeta (modo B)
    # ------------------------------------------------------------------
    def terminal_prepare_payment(self, payment_method, order, amount):
        listo = {'state': 'ready', 'amount': amount}
        if not self._promo_activo(payment_method):
            return listo
        if order.getnet_promocion_id:
            # Ya hay promoción (elegida o leída): se cobra el total y sólo el
            # total, restringido a la tarjeta (lo pone el payload).
            motivo = order._getnet_motivo_pago_dividido(amount)
            if motivo:
                return {'state': 'rejected', 'level': 'warning', 'message': _(
                    '%s Cobrá el total con la tarjeta, o quitá la promoción '
                    'para dividir el pago.', motivo)}
            return listo
        if (payment_method.getnet_modo_promociones != 'auto'
                or order.getnet_promocion_manual
                or not self._promo_hay_catalogo(order)
                or not self._promo_moneda_ok(payment_method, order)):
            return listo
        motivo = order._getnet_motivo_pago_dividido(amount)
        if motivo:
            order._getnet_registrar('pago_dividido', detalle=motivo)
            return dict(listo, level='warning', message=_(
                '%s Se cobra sin promoción.', motivo))
        return self._promo_iniciar_lectura(payment_method, order, amount)

    def _promo_iniciar_lectura(self, payment_method, order, amount):
        Lectura = self.env['getnet.lectura.tarjeta'].sudo()
        try:
            terminal = self._getnet_terminal(payment_method)
            if terminal.lock_origin and terminal.lock_origin != 'pos_backend':
                return self._promo_pasar_a_manual(order, _(
                    'la terminal está ocupada por otra operación'))
            provider = terminal.payment_provider_id
            vals = provider._getnet_base_transaccion_vals(terminal)
            # MontoTAP: con contactless la lectura necesita el importe (manual,
            # control de cambios v1.1). Va el total SIN promoción: es lo que
            # se sabe antes de leer. Ver doc/promociones.md, «Contactless».
            vals['MontoTAP'] = getnet_utils.getnet_centavos(amount)
            campos = {k: v for k, v in vals.items() if k in supuestos.CAMPOS_CONSULTA}
            data, _req, resp = provider._getnet_soap_transaccion(
                supuestos.METODO_POSTEAR, {supuestos.PARAMETRO_POSTEAR: campos})
        except Exception as error:  # noqa: BLE001 - cualquier falla pasa a A
            _logger.exception('Getnet promociones: falló el posteo de la lectura')
            return self._promo_pasar_a_manual(order, str(error))
        lectura = Lectura.create({
            'order_id': order.id,
            'payment_method_id': payment_method.id,
            'terminal_id': terminal.id,
            'token': str(data.get('TokenNro') or ''),
            'respuesta': _sanear_xml(resp),
        })
        rc = getnet_utils.getnet_rc(data)
        if rc != getnet_utils.GETNET_RC_OK or not data.get('TokenNro'):
            return self._promo_pasar_a_manual(order, _(
                'el concentrador no aceptó la lectura (%(rc)s): %(msg)s',
                rc=rc, msg=data.get('Resp_MensajeError') or _('sin token')), lectura)
        return {'state': 'waiting', 'token': str(lectura.id), 'level': 'info',
                'message': _('Pasá la tarjeta por el pinpad para ver si tiene promoción.')}

    def terminal_prepare_payment_poll(self, payment_method, order, token):
        try:
            lectura = self.env['getnet.lectura.tarjeta'].sudo().browse(int(token)).exists()
        except (TypeError, ValueError):
            lectura = None
        if not lectura or lectura.order_id != order:
            return self._promo_pasar_a_manual(order, _('lectura desconocida'))
        if lectura.state == 'fallida':
            return {'state': 'fallback'}
        if lectura.state == 'leida':
            return {'state': 'ready', 'amount': order.amount_pending}
        segundos = (fields.Datetime.now() - lectura.create_date).total_seconds()
        if segundos > supuestos.LECTURA_TOPE_SEGUNDOS:
            return self._promo_pasar_a_manual(
                order, _('no se pasó la tarjeta a tiempo'), lectura)
        try:
            provider = lectura.terminal_id.payment_provider_id
            data, _req, resp = provider._getnet_soap_transaccion(
                supuestos.METODO_CONSULTAR,
                {supuestos.PARAMETRO_CONSULTAR_TOKEN: lectura.token})
        except Exception as error:  # noqa: BLE001
            _logger.exception('Getnet promociones: falló la consulta de la lectura')
            return self._promo_pasar_a_manual(order, str(error), lectura)
        rc = getnet_utils.getnet_rc(data)
        if rc != getnet_utils.GETNET_RC_OK:
            lectura.respuesta = _sanear_xml(resp)
            return self._promo_pasar_a_manual(order, _(
                'la lectura devolvió un error (%(rc)s): %(msg)s',
                rc=rc, msg=data.get('Resp_MensajeError') or '-'), lectura)
        tarjeta = self._promo_tarjeta_de_datos(data)
        finalizada = any(getnet_utils.getnet_bool(data, b) for b in supuestos.BANDERAS_FINALIZADO)
        if not finalizada and not any(tarjeta.values()):
            return {'state': 'waiting', 'token': token}
        # Lo que devolvió el pinpad, sin datos sensibles: el BIN sí, que es lo
        # que hace falta para diagnosticar la primera venta real.
        _logger.info('Getnet promociones: lectura %s de %s: %s',
                     lectura.id, order.name, _sanear_datos(data))
        lectura.write({'respuesta': _sanear_xml(resp)})
        if not (tarjeta['tarjeta_id'] or tarjeta['emisor_id'] or tarjeta['iin']):
            return self._promo_pasar_a_manual(
                order, _('la respuesta no trae datos de la tarjeta'), lectura)
        lectura.write({'state': 'leida', 'datos': json.dumps(tarjeta),
                       'fecha_lectura': fields.Datetime.now()})
        promocion = self.env['getnet.promocion']._buscar(tarjeta, order.company_id)
        if not promocion:
            order._getnet_registrar('sin_promo', tarjeta=tarjeta)
            return {'state': 'ready', 'amount': order.amount_pending, 'level': 'info',
                    'message': _('La tarjeta no tiene promoción: se cobra el total.')}
        try:
            descuento = order._getnet_aplicar_promocion(promocion, 'auto', tarjeta)
        except UserError as error:
            return self._promo_pasar_a_manual(order, str(error), lectura)
        return {'state': 'ready', 'amount': order.amount_pending, 'level': 'success',
                'message': _('Promoción «%(promo)s»: −%(desc).2f. Se cobra %(total).2f '
                             'con la misma tarjeta.', promo=promocion.name,
                             desc=descuento, total=order.amount_pending)}

    # ------------------------------------------------------------------
    # La restricción a la tarjeta, en el posteo del cobro
    # ------------------------------------------------------------------
    def _getnet_authorize_inner(self, env, payment_method_id, amount, currency, reference):
        return super(PosBackendTerminalGetnet, self.with_context(
            getnet_promo_referencia=reference))._getnet_authorize_inner(
                env, payment_method_id, amount, currency, reference)

    def _getnet_payload_venta(self, provider, terminal, amount, currency):
        vals = super()._getnet_payload_venta(provider, terminal, amount, currency)
        referencia = self.env.context.get('getnet_promo_referencia')
        if not referencia:
            return vals
        # La referencia del POS es «<pedido>-<n>».
        order = provider.env['pos_backend.order'].sudo().search(
            [('name', '=', referencia.rsplit('-', 1)[0])], limit=1)
        promocion = order.getnet_promocion_id
        if not promocion:
            return vals
        if order.getnet_promocion_modo == 'auto':
            tarjeta = order._getnet_tarjeta_restringida()
            restriccion = {}
            if tarjeta.get('tarjeta_id'):
                restriccion['TarjetaId'] = int(float(tarjeta['tarjeta_id']))
            if tarjeta.get('emisor_id'):
                restriccion['EmisorId'] = int(float(tarjeta['emisor_id']))
            if tarjeta.get('tarjeta_tipo') in ('CRE', 'DEB'):
                restriccion['TarjetaTipo'] = tarjeta['tarjeta_tipo']
        else:
            restriccion = promocion._restriccion()
        vals.update(restriccion)
        return vals

    # ------------------------------------------------------------------
    # 8b · Opciones del medio: la selección manual (modo A)
    # ------------------------------------------------------------------
    def _promo_modo_manual(self, payment_method, order):
        modo = payment_method.getnet_modo_promociones
        return modo == 'manual' or (modo == 'auto' and order.getnet_promocion_manual)

    def terminal_payment_options(self, payment_method, order):
        if not self._promo_activo(payment_method) or not self._promo_modo_manual(payment_method, order):
            return []
        opciones = [{
            'key': 'promo_%s' % promo.id,
            'label': _('Getnet · %s', promo.name),
            'detail': promo._describir(),
            'active': promo == order.getnet_promocion_id,
        } for promo in self.env['getnet.promocion']._vigentes(order.company_id)]
        if order.getnet_promocion_id:
            opciones.append({'key': 'sin_promo', 'label': _('Sin promoción'),
                             'detail': '', 'active': False})
        return opciones

    def terminal_payment_option_apply(self, payment_method, order, option_key):
        if not self._promo_modo_manual(payment_method, order):
            raise UserError(_('Este medio no está en selección manual de promociones.'))
        if option_key == 'sin_promo':
            order._getnet_quitar_promocion(motivo=_('El cajero eligió «Sin promoción».'))
            return {'message': _('Promoción quitada.')}
        try:
            promo_id = int(option_key.split('_', 1)[1])
        except (IndexError, ValueError):
            raise UserError(_('Opción desconocida.'))
        promocion = self.env['getnet.promocion']._vigentes(order.company_id).filtered(
            lambda p: p.id == promo_id)
        if not promocion:
            raise UserError(_('La promoción ya no está vigente.'))
        motivo = order._getnet_motivo_pago_dividido()
        if motivo:
            raise UserError(motivo)
        descuento = order._getnet_aplicar_promocion(promocion, 'manual')
        return {'message': _(
            'Promoción «%(promo)s»: −%(desc).2f. Cobrá %(total).2f con esa '
            'tarjeta; el pinpad sólo va a aceptar %(tarjeta)s.',
            promo=promocion.name, desc=descuento, total=order.amount_pending,
            tarjeta=promocion._describir().split('·', 1)[-1].strip())}

    # ------------------------------------------------------------------
    # 8c · Avisos: la verificación contra el cobro aprobado
    # ------------------------------------------------------------------
    def _promo_tarjeta_de_linea(self, linea):
        """La tarjeta que aprobó el cobro de ``linea``, o None.

        SE LEE EN UN CURSOR PROPIO, y no es prolijidad: el cobro lo commitea
        el cursor propio de la autorización DURANTE el mismo request que
        después arma la pantalla (add_payment_line), y ese request corre en
        REPEATABLE READ con una foto tomada antes. Desde el cursor del
        request la transacción no existe todavía, y el aviso de PROMO NO
        APLICADA salía vacío justo en el cobro que lo tenía que mostrar.
        """
        referencia = linea.transaction_reference

        def leer(env):
            tx = env['payment.transaction'].sudo().search([
                ('getnet_pos_backend_reference', '=', referencia),
                ('provider_id.code', '=', 'getnet'),
            ], limit=1, order='id desc')
            return tx.getnet_tarjeta_aprobada() if tx else None
        return self._getnet_en_cursor_propio(leer)

    def _promo_registrar_una_vez(self, order, evento, ticket, **kw):
        if not order.getnet_promocion_evento_ids.filtered(
                lambda e: e.evento == evento and e.ticket == ticket):
            order._getnet_registrar(evento, ticket=ticket, **kw)

    def terminal_order_notices(self, payment_method, order):
        if not self._promo_activo(payment_method):
            return []
        vivos = order._getnet_cobros_vivos()
        propios = vivos.filtered(lambda l: l.payment_method_id == payment_method)
        autorizadas = propios.filtered(lambda l: l.integration_state == 'autorizado')
        promocion = order.getnet_promocion_id
        avisos = []
        for linea in autorizadas:
            tarjeta = self._promo_tarjeta_de_linea(linea)
            if tarjeta is None:
                continue
            ticket = linea.transaction_id or ''
            clave = '%s:%s' % (AVISO, linea.id)
            if promocion and not promocion._califica(tarjeta):
                self._promo_registrar_una_vez(order, 'no_coincide', ticket, tarjeta=tarjeta)
                avisos.append({
                    'key': clave, 'level': 'danger', 'blocking': True,
                    'text': _('PROMO NO COINCIDE: la promoción «%(promo)s» no es '
                              'para la tarjeta que pagó (%(tarjeta)s). Hay que '
                              'reversar el cobro y cobrar sin promoción.',
                              promo=promocion.name,
                              tarjeta=order._getnet_describir_tarjeta(tarjeta) or '?'),
                    'actions': [{'key': 'reversar_sin_promo',
                                 'label': _('Reversar (DEV) y cobrar sin promo')}],
                })
            elif promocion and len(vivos) > 1:
                avisos.append({
                    'key': clave, 'level': 'danger', 'blocking': True,
                    'text': _('PAGO DIVIDIDO: la promoción «%s» exige pagar el '
                              'total con la tarjeta. Quitá el otro cobro, o '
                              'reversá y cobrá sin promoción.', promocion.name),
                    'actions': [{'key': 'reversar_sin_promo',
                                 'label': _('Reversar (DEV) y cobrar sin promo')}],
                })
            elif not promocion and len(vivos) == 1 and ticket != order.getnet_promocion_ticket_ok:
                califica = self.env['getnet.promocion']._buscar(tarjeta, order.company_id)
                if califica:
                    self._promo_registrar_una_vez(order, 'no_aplicada', ticket,
                                                  promocion=califica, tarjeta=tarjeta)
                    avisos.append({
                        'key': clave, 'level': 'warning', 'blocking': True,
                        'text': _('PROMO NO APLICADA: la tarjeta que pagó '
                                  '(%(tarjeta)s) tenía «%(promo)s» (%(desc)s).',
                                  tarjeta=order._getnet_describir_tarjeta(tarjeta),
                                  promo=califica.name, desc=califica._describir()),
                        'actions': [
                            {'key': 'seguir_sin_promo', 'label': _('Seguir sin promo')},
                            {'key': 'reversar_con_promo',
                             'label': _('Reversar (DEV) y cobrar con promo')},
                        ],
                    })
        if promocion and not autorizadas:
            otros = vivos - propios.filtered(lambda l: l.integration_state == 'pendiente')
            avisos.append({
                'key': '%s:aplicada' % AVISO,
                'level': 'danger' if otros else 'info',
                'blocking': bool(otros),
                'text': _('Promoción «%(promo)s» aplicada. Exige cobrar el total '
                          'con %(tarjeta)s. Si la tarjeta fue rechazada o se va '
                          'a pagar de otra forma, quitala.',
                          promo=promocion.name,
                          tarjeta=promocion._describir().split('·', 1)[-1].strip()),
                'actions': [{'key': 'quitar_promo', 'label': _('Quitar promo')}],
            })
        return avisos

    def terminal_notice_action(self, payment_method, order, notice_key, action_key):
        app = self.env['pos_backend.app']
        promocion = order.getnet_promocion_id
        if action_key == 'quitar_promo':
            order._getnet_quitar_promocion(motivo=_('Quitada por el cajero desde el aviso.'))
            return {'message': _('Promoción quitada: se cobra el total.')}
        try:
            linea_id = int(notice_key.rsplit(':', 1)[1])
        except (IndexError, ValueError):
            raise UserError(_('Aviso desconocido.'))
        linea = order.payment_line_ids.filtered(lambda l: l.id == linea_id)
        if not linea:
            raise UserError(_('El cobro del aviso ya no está en el pedido.'))
        tarjeta = self._promo_tarjeta_de_linea(linea) or {}
        ticket = linea.transaction_id or ''
        if action_key == 'seguir_sin_promo':
            order.sudo().getnet_promocion_ticket_ok = ticket
            order._getnet_registrar('seguir_sin_promo', ticket=ticket, tarjeta=tarjeta)
            return {'message': _('Se sigue sin promoción; queda registrado en el pedido.')}
        if action_key not in ('reversar_sin_promo', 'reversar_con_promo'):
            raise UserError(_('Acción desconocida.'))
        # La reversa es la del POS (DEV contra el ticket, línea reversada con
        # su rastro). Si falla, el error sube y nada más cambia.
        app.reverse_payment_line(linea.id)
        order._getnet_registrar('reversada', promocion=promocion, ticket=ticket,
                                tarjeta=tarjeta, detalle=action_key)
        if action_key == 'reversar_sin_promo':
            order._getnet_quitar_promocion(motivo=_('Reversado: la tarjeta no coincidía.'))
            return {'message': _('Cobro reversado y promoción quitada: cobrá el total.')}
        califica = self.env['getnet.promocion']._buscar(tarjeta, order.company_id)
        if not califica:
            return {'message': _('Cobro reversado. La promoción ya no está vigente: '
                                 'cobrá el total.')}
        descuento = order._getnet_aplicar_promocion(califica, 'auto', tarjeta)
        return {'message': _(
            'Cobro reversado y promoción «%(promo)s» aplicada (−%(desc).2f): cobrá '
            '%(total).2f con la misma tarjeta.', promo=califica.name,
            desc=descuento, total=order.amount_pending)}
