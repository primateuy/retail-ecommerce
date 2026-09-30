# -*- coding: utf-8 -*-
"""
payment.transaction extendida para Fiserv ITD + bucle de consultas.

Ciclo ITD: processFinancialPurchase (o void/refund) -> TransactionId ->
processFinancialPurchaseQuery en bucle hasta una respuesta final ->
persistir ticket/lote/autorización/tarjeta.

Regla que ordena todo este archivo: **un cobro que quizás existió nunca
pierde el rastro**. La transacción se crea ANTES de hablar con ITD (la crea
el flujo que la origina) y un fallo de transporte la deja ``pending`` —a la
vista y reconsultable—, jamás ``error``.
"""

import json
import logging
import time

from odoo import _, fields, models
from odoo.exceptions import AccessError

from . import fiserv_utils

_logger = logging.getLogger(__name__)

# Códigos de respuesta del POSLink (Anexo 1 - ResponseCode PLS). Documentación: Especificaciones POSLink v135.
RESPONSE_CODE_MESSAGES = {
    '0': 'OK',
    '10': 'Esperando respuesta del pinpad',
    '11': 'Tiempo excedido',
    '12': 'Pinpad consultó datos',
    '100': 'Pinpad inválido',
    '101': 'Pinpad no existe',
    '102': 'Pinpad no responde',
    '103': 'Pinpad en uso',
    '104': 'Monto no válido',
    '105': 'Cuotas inválidas',
    '106': 'Tipo de transacción inválido',
    '107': 'Error en datos enviados',
    '108': 'Error en comunicación',
    '109': 'Error en pinpad',
    '110': 'Error en sistema',
    '111': 'Error en autorización',
    '112': 'Error en reverso',
    '113': 'Error en cierre',
    '999': 'Error no determinado',
    '-100': 'Formato en campo/s incorrecto; faltan campos obligatorios',
}

# Códigos aprobados del terminal (ITD / posResponseCode). Cualquier otro código = rechazo/error.
POS_APPROVED_CODES = ('0', '00', '08', '10', '11', '85', 'OF', 'Y1', 'Y3')

# Mensajes del terminal (Anexo 2 - posResponseCode). Documentación: Especificaciones POSLink v135.
POS_RESPONSE_CODE_MESSAGES = {
    '00': 'Aprobado. APROBADA',
    '01': 'Contacte al emisor, en caso de ser aprobada realizar operación offline. PEDIR AUTORIZACION',
    '02': 'Idem al anterior. PEDIR AUTORIZACION',
    '03': 'Comercio inválido. COMERCIO INVALIDO',
    '04': 'Retener tarjeta. RETENER TARJETA',
    '05': 'Transacción negada. DENEGADA',
    '06': 'Error (utilizado en transferencia de archivos). N/A',
    '07': 'Retenga y llame. RETENGA Y LLAME',
    '08': 'Aprobado EMV (Mastercard). APROBADA EMV',
    '10': 'Aprobado Parcialmente (CashBack). APROBADO SOLO VENTAS',
    '11': 'Aprobado (igual que 00). APROBADA',
    '12': 'Transacción inválida. TRANSAC. INVALIDA',
    '13': 'Monto inválido. MONTO INVALIDO',
    '14': 'Tarjeta inválida o cédula no corresponde con titular. TARJETA INVALIDA',
    '15': 'Emisor no valido. EMISOR NO VALIDO',
    '21': 'No se tomó acción (reversas y anulaciones). NO EXISTE ORIGINAL',
    '25': 'No existe original, registro no encontrado en archivo de transacciones. NO EXISTE ORIGINAL',
    '30': 'Error en formato del mensaje. ERROR EN FORMATO',
    '31': 'Tarjeta no soportada. CARD NOT SUPPORTED',
    '38': 'Denegada, excede cantidad de reintentos de PIN permitida. EXCEDE ING. DE PIN',
    '39': 'Rechazada (código no especificado en documentación). RECHAZADA',
    '41': 'Tarjeta perdida, retener. PERDIDA, RETENER',
    '43': 'Tarjeta robada, retener. ROBADA, RETENER',
    '45': 'Tarjeta inhabilitada para operar en cuotas. NO OPERA EN CUOTAS',
    '46': 'Tarjeta no vigente. TARJETA NO VIGENTE',
    '47': 'PIN requerido. PIN REQUERIDO',
    '48': 'Excede cantidad máxima de cuotas permitidas. EXCEDE MAX. CUOTAS',
    '49': 'Error en formato de fecha de expiración. ERROR FECHA VENCIM',
    '50': 'Monto ingresado en entrega supera limite. ENTREGA SUPERA LIM',
    '51': 'Sin disponible. SALDO INSUFICIENTE',
    '53': 'Cuenta inexistente. CTA. INEXISTENTE',
    '54': 'Tarjeta vencida. TARJETA VENCIDA',
    '55': 'PIN incorrecto. PIN INCORRECTO',
    '56': 'Emisor no habilitado en el sistema. TARJ.NO HABILITADA',
    '57': 'Transacción no permitida a esta tarjeta. TRANS.NO PERMITIDA',
    '58': 'Servicio inválido. Transacción no permitida a la terminal. SERVICIO INVALIDO',
    '59': 'Sospecha de fraude. SOSPECHA DE FRAUDE',
    '61': 'Excede monto límite de actividad - Contacte al emisor. EXCEDE MONTO LIMIT',
    '62': 'Tarjeta restringida para dicha terminal u operacion. TARJETA RESTRINGIDA',
    '65': 'Límite de actividad excedido – Contacte al emisor. EXCEDE LIM.TARJETA',
    '76': 'Solicitar autorización telefónica. LLAMAR AL EMISOR',
    '77': 'Error en plan/cuotas. ERROR PLAN/CUOTAS',
    '78': 'Debe cambiar Pin. DEBE CAMBIAR PIN',
    '81': 'Error criptográfico en manejo de pin online. ERROR CRIPTOGRAFICO',
    '82': 'Error en validación de CVV. CVV INVALIDO',
    '83': 'Imposible verificar PIN en manejo de pin online. IMPOSIBLE VERIFICAR PIN',
    '84': 'Moneda Invalida. MONEDA INVALIDA',
    '85': 'Aprobado. APROBADA',
    '89': 'Terminal inválida. TERMINAL INVALIDA',
    '91': 'Emisor no responde. EMISOR NO RESPONDE',
    '94': 'Número de secuencia duplicado. NRO. SEC.DUPLICADO',
    '95': 'Diferencia en el cierre de transacciones. RE-TRANSMITIENDO',
    '96': 'Error de sistema. ERROR EN SISTEMA',
    '98': 'Mensajes Especiales. MENSAJES ESPECIALES',
    'CE': 'Error en conexión al Host.',
    'CF': 'Consulta Caja Fallido.',
    'CT': 'Cancelar Transacción.',
    'EA': 'Error en código de comercio.',
    'EB': 'Error en Batch (Lote).',
    'EC': 'Error en Cierre de lote.',
    'EE': 'Error Rutinas EMV.',
    'EI': 'Error en Información enviada al PinPad.',
    'ER': 'Error enviando Reverso al Autorizador.',
    'ET': 'Error en Ingreso Inicial de Datos.',
    'LL': 'Lote Lleno.',
    'LV': 'Lote Vacío.',
    'MK': 'MasterKey Ausente.',
    'N7': 'CVV2 no válido. CVV2 NO VALIDO',
    'NC': 'No responde Caja a Mensaje Inicial.',
    'NP': 'Operación NO Permitida.',
    'NR': 'No responde Autorizador.',
    'OF': 'Aprobación Offline. APROBADA OFFLINE',
    'TI': 'Tarjeta incorrecta.',
    'TN': 'Tarjeta Incorrecta en Offline.',
    'TP': 'Transacción Pendiente (usado por billeteras). TRANS. PENDIENTE',
    'TO': 'TimeOut Ingreso Tarjeta.',
    'XX': 'Cualquier otro código no especificado, denegada. RECHAZADA',
}

# Respuestas intermedias del Query: la operación sigue viva en el pinpad.
FISERV_RC_EN_CURSO = ('10', '12')
# Espera entre consultas (valor histórico de 17.0).
FISERV_POLL_WAIT = 4
# Tope del bucle. En 17.0 eran 900 vueltas × 4 s (~1 h) contadas por
# iteración; ahora es tiempo real, así que una vuelta lenta (timeout HTTP de
# 30 s) no estira el tope sin control. Pasado esto la transacción queda
# ``pending`` para verificación: NUNCA ``error``. En condiciones normales el
# bucle termina mucho antes, por respuesta final o por el vencimiento que
# informa ITD (RemainingExpirationTime -> reverse).
FISERV_POLL_HARD_MAX = 15 * 60


class PaymentTransaction(models.Model):
    """
    Extensión del modelo payment.transaction para Fiserv ITD.

    Agrega campos para datos del pinpad y auditoría JSON.
    """
    _inherit = 'payment.transaction'

    # Campos específicos de Fiserv ITD
    pos_id = fields.Char(
        string='POS ID',
        copy=False,
        help='Identificador del punto de venta (PosID)'
    )
    card_bin = fields.Char(
        string='BIN de Tarjeta',
        copy=False,
        help='Primeros 6 números de la tarjeta'
    )
    card_last_four = fields.Char(
        string='Últimos 4 dígitos',
        copy=False,
        help='Últimos 4 dígitos de la tarjeta'
    )
    issuer_code = fields.Char(
        string='Código del Emisor',
        copy=False,
        help='Código del emisor de la tarjeta'
    )
    issuer_name = fields.Char(
        string='Nombre del Emisor',
        copy=False,
        help='Nombre del emisor de la tarjeta'
    )
    installments = fields.Integer(
        string='Cantidad de Cuotas',
        copy=False,
        help='Número de cuotas de la transacción'
    )
    acquirer = fields.Char(
        string='Adquirente',
        copy=False,
        help='Proveedor de pago (Acquirer)'
    )
    ticket_number = fields.Char(
        string='Número de Ticket',
        copy=False,
        help='Número de ticket de la transacción'
    )
    batch_number = fields.Char(
        string='Número de Lote',
        copy=False,
        help='Número de lote de la transacción'
    )
    authorization_code = fields.Char(
        string='Código de Autorización',
        copy=False,
        help='Código de autorización de la transacción'
    )
    transaction_origin = fields.Selection([
        ('pos_payment', 'Pago POS'),
        ('pos_order', 'Pedido POS'),
        ('account_payment', 'Pago contable'),
        ('other', 'Otro'),
    ], string='Origen de Transacción', default='pos_payment', copy=False)
    account_payment_id = fields.Many2one(
        comodel_name='account.payment',
        string='Pago contable',
        ondelete='set null',
        index=True,
        copy=False,
        help='Registro de pago estándar (account.payment) cuando el cobro ITD se inició desde contabilidad.',
    )
    is_promotion = fields.Boolean(
        string='Es Promoción',
        copy=False,
        help='Indica si la transacción es una promoción'
    )
    merchant_number = fields.Char(
        string='Número de Comercio',
        copy=False,
        help='Número de comercio para el adquirente'
    )
    invoice_number = fields.Char(
        string='Número de Factura',
        copy=False,
        help='Número de factura enviado al POS'
    )
    # Campos de auditoría
    fiserv_transaction_id = fields.Char(
        string='ID transacción ITD',
        index=True,
        copy=False,
        help='TransactionId asignado por Fiserv ITD.',
    )
    fiserv_response_code = fields.Char(
        string='Código de respuesta ITD',
        copy=False,
        help='ResponseCode de la consulta o respuesta final.',
    )
    fiserv_response_message = fields.Text(
        string='Mensaje de respuesta',
        copy=False,
        help='Texto descriptivo para el usuario o soporte.',
    )
    fiserv_complete_request = fields.Text(
        string='Solicitud completa a ITD',
        copy=False,
        help='Solicitud enviada a ITD en formato JSON para auditoría (SystemId enmascarado).'
    )
    fiserv_complete_response = fields.Text(
        string='Respuesta completa de ITD',
        copy=False,
        help='Respuesta de ITD en formato JSON para auditoría.'
    )
    fiserv_requiere_conciliacion = fields.Boolean(
        string='Requiere verificación manual',
        index=True,
        copy=False,
        help='No se pudo saber el resultado de la operación (sin respuesta de ITD). '
             'Alguien tiene que verificarla contra el pinpad o el cierre de lote '
             'antes de reintentar o anular.',
    )
    fiserv_motivo_conciliacion = fields.Char(
        string='Motivo de verificación',
        copy=False,
    )

    # ------------------------------------------------------------------
    # Estado a partir de la respuesta ITD
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_itd_quota(val):
        """Normaliza el campo Quota devuelto por ITD (entero o texto con ceros)."""
        try:
            return int(str(val).strip() or 0)
        except (TypeError, ValueError):
            return 0

    def _get_transaction_state_from_response(self, response_code):
        """
        Estado según ResponseCode ITD.

        ``FISERV_RC_TRANSPORTE`` es ``pending``: no hubo respuesta usable y el
        pedido pudo haber llegado. Las respuestas intermedias (10/12) también.
        Cualquier otro código que no sea 0 es una respuesta de ITD que dice
        que no: ``error``.
        """
        if response_code == '0':
            return 'done'
        if response_code in FISERV_RC_EN_CURSO or response_code == fiserv_utils.FISERV_RC_TRANSPORTE:
            return 'pending'
        return 'error'

    def _get_transaction_state_with_pos_response(self, response_code, itd_response):
        """
        Estado considerando ResponseCode y posResponseCode: si el terminal
        rechazó (posResponseCode no aprobado), estado = error.
        """
        pos_code = itd_response.get('PosResponseCode') or itd_response.get('posResponseCode')
        pos_response_code = (
            str(pos_code).strip().upper()
            if pos_code is not None and pos_code != ''
            else None
        )
        if response_code == '0' and pos_response_code and pos_response_code not in POS_APPROVED_CODES:
            return 'error'
        return self._get_transaction_state_from_response(response_code)

    def _get_fiserv_display_message(self, itd_response):
        """
        Mensaje legible según ResponseCode y posResponseCode (Anexos 1 y 2
        POSLink v135). Prioriza el código del terminal cuando indica rechazo.
        """
        if not itd_response:
            return 'Error desconocido'
        if fiserv_utils.fiserv_is_transport_failure(itd_response):
            return itd_response.get('msg') or _('Sin respuesta de ITD.')
        pos_code = itd_response.get('PosResponseCode') or itd_response.get('posResponseCode')
        pos_response_code = (
            str(pos_code).strip().upper()
            if pos_code is not None and pos_code != ''
            else None
        )
        response_code = str(itd_response.get('ResponseCode', '')).strip()
        if pos_response_code and pos_response_code not in POS_APPROVED_CODES:
            return POS_RESPONSE_CODE_MESSAGES.get(
                pos_response_code,
                f'Rechazada por el terminal (código {pos_response_code})',
            )
        if response_code and response_code not in ('0',):
            return RESPONSE_CODE_MESSAGES.get(
                response_code,
                f'Error del sistema POSLink (código {response_code})',
            )
        return itd_response.get('msg', '') or 'Aprobado'

    # ------------------------------------------------------------------
    # Post-procesamiento nativo
    # ------------------------------------------------------------------
    def _create_payment(self, **extra_create_values):
        """
        Fiserv NUNCA auto-crea un account.payment.

        ``account_payment._post_process()`` llama a este método para toda
        transacción ``done`` sin ``payment_id`` y crea + postea un pago. Las
        nuestras cumplen esa condición, pero el pago ya existe (flujo
        contable: es el que originó el cobro y lo confirma el usuario a mano)
        o no corresponde (flujo TPV: el cobro es el pos.payment). Dejar que el
        core cree otro duplica el importe en los libros.
        """
        self.ensure_one()
        if self.provider_code == 'fiserv':
            _logger.info(
                'Fiserv: no se crea account.payment automático para la '
                'transacción %s (pago propio: %s).',
                self.reference, self.account_payment_id.id or 'ninguno')
            return self.account_payment_id
        return super()._create_payment(**extra_create_values)

    # ------------------------------------------------------------------
    # Verificación manual
    # ------------------------------------------------------------------
    def _fiserv_marcar_conciliacion(self, motivo):
        """Deja la transacción marcada para verificación humana."""
        self.ensure_one()
        # sudo: la marca la pone la máquina (worker o flujo), no el usuario.
        self.sudo().write({
            'fiserv_requiere_conciliacion': True,
            'fiserv_motivo_conciliacion': motivo,
        })
        _logger.error(
            'Fiserv: la transacción %s (ITD %s) requiere verificación manual: %s',
            self.reference, self.fiserv_transaction_id or '-', motivo)

    def fiserv_action_conciliada(self):
        """
        «Verificada: sin cobro»: alguien miró el pinpad / el cierre de lote y
        la operación NO existió. La transacción pendiente se cancela y el pago
        queda libre para volver a cobrar.

        Es un método PÚBLICO (lo llama un botón), así que se llega por RPC.
        La escritura va en sudo —el core sólo da escritura de
        payment.transaction a facturación/sistema— y la restricción real es
        esta guarda: sólo contabilidad puede darla por verificada.
        """
        if not self.env.su and not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_(
                'Solo un usuario de Contabilidad puede marcar una transacción '
                'Fiserv como verificada.'))
        for tx in self.sudo():
            tx.fiserv_requiere_conciliacion = False
            if tx.state in ('draft', 'pending'):
                tx._set_canceled(state_message=_(
                    'Verificada a mano por %s: sin cobro en el pinpad.', self.env.user.name))
        return True

    # ------------------------------------------------------------------
    # Bucle de consultas
    # ------------------------------------------------------------------
    def _fiserv_run_query_loop(self, driver, query_data, transaction_id,
                               original_purchase_data=None,
                               hard_max=FISERV_POLL_HARD_MAX):
        """
        Consulta processFinancialPurchaseQuery hasta una respuesta final.

        Si el cobro inicial llevó NeedToReadCard=True, ITD pasa por RC 10/12
        hasta leer la tarjeta y exige UN processConfirmFinancialPurchase para
        enviar al host; sin eso el pinpad queda en «Enviando al host».

        Reglas (las nuevas respecto de 17.0 están marcadas):
        - RC 10/12: la operación sigue viva, se sigue consultando.
        - Vencimiento informado por ITD (RemainingExpirationTime <= 0 con
          10/12): processFinancialReverse y resultado RC 11.
        - **NUEVO: un fallo de transporte NO corta el bucle.** En 17.0 un solo
          502 o timeout durante la espera devolvía 999 y la transacción
          quedaba en ``error`` definitivo, aunque el pinpad aprobara después.
        - **NUEVO: un fallo de transporte en el confirm NO corta el bucle.** El
          confirm pudo haber llegado: se sigue consultando y ITD dirá.
        - **NUEVO: agotado ``hard_max`` sin respuesta final, el resultado es
          ``FISERV_RC_TRANSPORTE`` con ``fiserv_timeout``** → ``pending``.

        ``driver`` expone ``_fiserv_timestamp``, ``_fiserv_itd_query``,
        ``_fiserv_itd_confirm`` y ``_fiserv_itd_reverse`` (hoy payment.provider).

        :return: dict con la última respuesta relevante.
        """
        driver.ensure_one()
        start = time.monotonic()
        result = {}
        last_itd = {}
        confirm_after_card_read_done = False
        need_read_card = bool(
            original_purchase_data and original_purchase_data.get('NeedToReadCard'))
        while True:
            time.sleep(FISERV_POLL_WAIT)
            query_data['TransactionDateTimeyyyyMMddHHmmssSSS'] = driver._fiserv_timestamp()
            result = driver._fiserv_itd_query(query_data)
            response_code = str(result.get('ResponseCode', '999')).strip()

            if response_code == fiserv_utils.FISERV_RC_TRANSPORTE:
                _logger.warning(
                    'Fiserv tx %s: sin respuesta de ITD en la consulta; se reintenta (%s).',
                    transaction_id, result.get('msg'))
            else:
                last_itd = result
                if (
                    need_read_card
                    and not confirm_after_card_read_done
                    and response_code == '12'
                    and fiserv_utils._fiserv_card_data_ready_for_confirm(result)
                ):
                    confirm_payload = fiserv_utils._fiserv_build_confirm_financial_purchase_payload(
                        original_purchase_data, result, transaction_id, driver)
                    _logger.info(
                        'Fiserv ITD: processConfirmFinancialPurchase tras RC=12 | tx=%s',
                        transaction_id)
                    conf = driver._fiserv_itd_confirm(confirm_payload)
                    # Se da por enviado también ante transporte: pudo haber
                    # llegado, y confirmar dos veces no es lo que pide ITD.
                    confirm_after_card_read_done = True
                    crc = str(conf.get('ResponseCode', '999')).strip()
                    if crc in ('999', '-100'):
                        return conf

                if response_code not in FISERV_RC_EN_CURSO:
                    return result

                rt_raw = result.get('RemainingExpirationTime', False)
                rt_num = None
                if rt_raw is not False and rt_raw is not None and rt_raw != '':
                    try:
                        rt_num = float(rt_raw)
                    except (TypeError, ValueError):
                        rt_num = None
                if rt_num is not None and rt_num <= 0:
                    _logger.warning(
                        'Tiempo de transacción expirado para %s. Reversión...', transaction_id)
                    reverse_result = driver._fiserv_itd_reverse(query_data)
                    timeout_result = {
                        'ResponseCode': '11',
                        'msg': 'Tiempo de transacción excedido, envíe datos nuevamente.',
                        'TransactionId': transaction_id,
                        'RemainingExpirationTime': 0.0,
                        'timeout_error': True,
                        'reverse_processed': True,
                        'reverse_success': reverse_result.get('ResponseCode') == '0',
                        'reverse_msg': reverse_result.get('msg', ''),
                    }
                    return timeout_result

            if time.monotonic() - start >= hard_max:
                _logger.error(
                    'Fiserv tx %s: sin respuesta final tras %ss; queda pendiente '
                    'para verificación manual (NO se marca como error).',
                    transaction_id, hard_max)
                timeout = dict(last_itd)
                timeout.update({
                    'ResponseCode': fiserv_utils.FISERV_RC_TRANSPORTE,
                    'TransactionId': transaction_id,
                    'fiserv_timeout': True,
                    'msg': _(
                        'Sin respuesta final de ITD tras %s segundos. Verificar el '
                        'pinpad antes de reintentar o anular.', hard_max),
                })
                return timeout

    # ------------------------------------------------------------------
    # Persistencia del resultado
    # ------------------------------------------------------------------
    def _fiserv_is_outbound_tx(self):
        """
        True si la transacción es una anulación o devolución (salida de
        dinero): se guarda ``amount`` con signo negativo.
        """
        self.ensure_one()
        if self.amount and self.amount < 0:
            return True
        if self.account_payment_id and self.account_payment_id.payment_type == 'outbound':
            return True
        return False

    def _fiserv_corrected_amount_from_total_amount(self, itd_response):
        """TotalAmount ITD (centavos) a importe Odoo; None si no aplica."""
        if 'TotalAmount' not in itd_response:
            return None
        try:
            total_amount = float(itd_response.get('TotalAmount', '0'))
        except (TypeError, ValueError):
            return None
        if total_amount <= 0:
            return None
        return total_amount / 100.0

    def _fiserv_persist_query_result(self, itd_response, pos_data=None):
        """
        Vuelca la respuesta final (o la de transporte) en la transacción y la
        transiciona con los helpers nativos de payment.transaction.

        Mapeo:
        - RC 0 y terminal aprobó          -> _set_done()
        - RC 0 y terminal rechazó / otro  -> _set_error()
        - transporte / tope / 10-12       -> _set_pending() + marca de verificación
        """
        self.ensure_one()
        response_code = str(itd_response.get('ResponseCode', '999')).strip()
        new_state = self._get_transaction_state_with_pos_response(response_code, itd_response)
        state_message = self._get_fiserv_display_message(itd_response)
        update_vals = {
            'fiserv_response_code': response_code,
            'fiserv_response_message': state_message,
            'fiserv_complete_response': json.dumps(itd_response, indent=2, ensure_ascii=False),
        }
        if pos_data:
            update_vals['fiserv_complete_request'] = json.dumps(
                fiserv_utils.fiserv_mask_payload(pos_data), indent=2, ensure_ascii=False)
        tid = str(itd_response.get('TransactionId') or '').strip()
        if tid and tid != '0':
            update_vals['fiserv_transaction_id'] = tid

        if new_state != 'pending':
            reference = self._generate_fiserv_reference_from_complete_data(itd_response)
            if reference and reference != self.reference and not self.search_count(
                    [('reference', '=', reference), ('id', '!=', self.id)]):
                update_vals['reference'] = reference

        corrected_amount = self._fiserv_corrected_amount_from_total_amount(itd_response)
        if corrected_amount is not None:
            # ITD devuelve TotalAmount positivo; una anulación/devolución se
            # guarda en negativo para reflejar la salida de dinero.
            if corrected_amount > 0 and self._fiserv_is_outbound_tx():
                corrected_amount = -corrected_amount
            update_vals['amount'] = corrected_amount

        if itd_response.get('PosID'):
            update_vals['pos_id'] = itd_response['PosID']
        if itd_response.get('Currency'):
            update_vals['currency_id'] = self._get_currency_id_from_response(itd_response)
        if itd_response.get('Quota') is not None and itd_response.get('Quota') != '':
            update_vals['installments'] = self._parse_itd_quota(itd_response.get('Quota', 0))
        if itd_response.get('CardNumber'):
            card_num = str(itd_response['CardNumber'])
            if len(card_num) >= 10:
                update_vals.update({'card_bin': card_num[:6], 'card_last_four': card_num[-4:]})
            elif len(card_num) >= 6:
                update_vals.update({'card_bin': card_num[:6], 'card_last_four': ''})
        if itd_response.get('Issuer'):
            if isinstance(itd_response['Issuer'], dict):
                update_vals.update({
                    'issuer_code': itd_response['Issuer'].get('code', ''),
                    'issuer_name': itd_response['Issuer'].get('name', ''),
                })
            else:
                update_vals['issuer_code'] = str(itd_response['Issuer'])
                update_vals['issuer_name'] = self._get_fiserv_card_brand_display_name(itd_response)
        if (itd_response.get('EmvApplicationName') or '').strip():
            update_vals['issuer_name'] = self._get_fiserv_card_brand_display_name(itd_response)
        if itd_response.get('Acquirer') is not None and itd_response.get('Acquirer') != '':
            update_vals['acquirer'] = str(itd_response['Acquirer'])
        for key, field_name in (
            ('Ticket', 'ticket_number'),
            ('Batch', 'batch_number'),
            ('AuthorizationCode', 'authorization_code'),
            ('Merchant', 'merchant_number'),
        ):
            if itd_response.get(key):
                update_vals[field_name] = itd_response[key]
        self.write(update_vals)

        if new_state == 'done':
            self._set_done(state_message=state_message)
            if self.fiserv_requiere_conciliacion:
                self.sudo().write({'fiserv_requiere_conciliacion': False})
        elif new_state == 'error':
            self._set_error(state_message)
            if self.fiserv_requiere_conciliacion:
                self.sudo().write({'fiserv_requiere_conciliacion': False})
        else:
            if self.state == 'pending':
                self.state_message = state_message
            else:
                self._set_pending(state_message=state_message)
            if fiserv_utils.fiserv_is_transport_failure(itd_response):
                self._fiserv_marcar_conciliacion(state_message)
        return self.state

    def _generate_fiserv_reference_from_complete_data(self, itd_response):
        """Referencia legible con PosID/ticket/lote/autorización/fecha."""
        pos_id = str(itd_response.get('PosID', '') or '').strip()
        ticket = str(itd_response.get('Ticket', '') or '').strip()
        batch = str(itd_response.get('Batch', '') or '').strip()
        authorization = str(itd_response.get('AuthorizationCode', '') or '').strip()
        transaction_date = str(itd_response.get('TransactionDate', '') or '').strip()
        transaction_hour = str(itd_response.get('TransactionHour', '') or '').strip()
        parts = ['FISERV', pos_id, ticket, batch, authorization, transaction_date, transaction_hour]
        reference = '-'.join(p for p in parts if p)
        tid = str(itd_response.get('TransactionId', '') or '').strip()
        if tid and reference in ('FISERV', ''):
            reference = f'FISERV-{tid}'
        return reference

    def _get_currency_id_from_response(self, itd_response):
        """Moneda Odoo desde el código ITD (858 UYU / 840 USD)."""
        currency_mapping = {'858': 'UYU', '840': 'USD'}
        currency_name = currency_mapping.get(str(itd_response.get('Currency', '858')), 'UYU')
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', currency_name)], limit=1)
        return currency.id if currency else self.env.company.currency_id.id

    def _get_fiserv_card_brand_display_name(self, itd_response):
        """
        Nombre de marca (sello) para mostrar.

        Prioridad (decisión 2026-06-17):
          1) Marca CONFIGURADA en el proveedor según el código de Issuer (Anexo 4 POSLink).
          2) Nombre EMV del pinpad (`EmvApplicationName`).
          3) Fallback al mapeo histórico (`_get_fiserv_issuer_name`).
        """
        issuer_code = itd_response.get('Issuer') if isinstance(itd_response, dict) else itd_response
        brand_name = self._brand_name_from_provider_code(
            'odoo_pos_fiserv_core.payment_method_fiserv', issuer_code)
        if brand_name:
            return brand_name
        if not isinstance(itd_response, dict):
            return self._get_fiserv_issuer_name(itd_response)
        emv_name = (itd_response.get('EmvApplicationName') or '').strip()
        if emv_name:
            return emv_name
        return self._get_fiserv_issuer_name(itd_response.get('Issuer'))

    def _normalize_issuer_code(self, issuer_code):
        """Código de issuer al formato del Anexo 4 (2 dígitos; ej. 2 -> '02')."""
        if issuer_code in (None, False, ''):
            return ''
        try:
            return str(int(issuer_code)).zfill(2)
        except (TypeError, ValueError):
            return str(issuer_code).strip()

    def _brand_name_from_provider_code(self, primary_method_xmlid, issuer_code):
        """Marca (payment.method hija del método Fiserv) configurada para ese código."""
        code = self._normalize_issuer_code(issuer_code)
        if not code:
            return ''
        method = self.env.ref(primary_method_xmlid, raise_if_not_found=False)
        if not method:
            return ''
        brand = self.env['payment.method'].sudo().with_context(active_test=False).search([
            ('primary_payment_method_id', '=', method.id),
            ('code', '=', code),
        ], limit=1)
        return brand.name if brand else ''

    def _get_fiserv_issuer_name(self, issuer_code):
        """Nombre del emisor por código (mapeo parcial histórico)."""
        issuer_mapping = {
            21: 'OCA',
            5: 'Visa',
            6: 'Mastercard',
            7: 'American Express',
            24: 'Visa',
            52: 'Mastercard',
        }
        try:
            code_int = int(issuer_code)
        except (TypeError, ValueError):
            return str(issuer_code) if issuer_code is not None else ''
        mapped_name = issuer_mapping.get(code_int)
        if mapped_name:
            payment_method = self.env['payment.method'].sudo().search([
                ('name', 'ilike', mapped_name)
            ], limit=1)
            if payment_method:
                return payment_method.name
        return mapped_name or f'Emisor {issuer_code}'
