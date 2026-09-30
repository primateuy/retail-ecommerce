# -*- coding: utf-8 -*-
"""
Utilidades y constantes compartidas de la integración Fiserv ITD.

Funciones puras (sin modelos Odoo): transporte HTTP contra ITD, normalización
de respuestas, armado del confirm y guard de commits. Todo lo que toca modelos
vive en payment_provider.py / payment_transaction.py.
"""

import copy
import logging
import pprint
import threading

import requests

from odoo.tools import config

_logger = logging.getLogger(__name__)

# Mensajes ITD alineados con la tabla de códigos de respuesta del servicio
# (processFinancial*, cancel, reverse).
FISERV_ITD_RESPONSE_CODE_MSG = {
    '0': 'Resultado OK',
    '10': 'Aguardando por operación en el pinpad.',
    '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
    '12': 'Pinpad consultó datos (se pasó la tarjeta o Poleo Automático).',
    '100': 'Número de pinpad inválido',
    '101': 'Número de sucursal inválido',
    '102': 'Número de caja inválido',
    '103': 'Fecha de la transacción inválida',
    '104': 'Monto no válido',
    '105': 'Cantidad de cuotas inválidas',
    '106': 'Número de plan inválido',
    '107': 'Número de factura inválido',
    '108': 'Moneda ingresada no válida',
    '109': 'Número de ticket inválido.',
    '110': 'No existe transacción.',
    '111': 'Transacción finalizada.',
    '112': 'Identificador de sistema inválido.',
    '113': 'Se debe consultar por la transacción',
    '999': 'Error no determinado.',
    '-100': 'Formato en campo/s incorrecta; Faltan campos obligatorios',
}

# Código SINTÉTICO nuestro, no existe en la especificación ITD: no hubo una
# respuesta usable de ITD (timeout, error de conexión, HTTP 5xx, cuerpo que no
# es JSON). NO es un rechazo: el pedido pudo haber llegado igual y haber una
# operación viva en el pinpad. Quien lo reciba no puede cerrar nada como
# error; la transacción queda pendiente, a la vista, hasta que alguien la
# verifique. Es el DL-6 de Getnet, del lado Fiserv.
FISERV_RC_TRANSPORTE = 'TRANSPORTE'

# Estados HTTP que NO son una respuesta de ITD sino del camino hasta ITD: el
# pedido puede haber llegado o no. Un 4xx distinto de estos sí es una
# negativa del servicio (URL mal armada, campo inválido): ahí no hay nada en
# el pinpad.
FISERV_HTTP_TRANSPORTE = (408, 429)

# Timeout en DOS TRAMOS (lección DL-7 de Getnet): conectar es rápido o no va a
# pasar; leer es donde ITD trabaja, y se conserva el valor histórico de 30 s.
FISERV_HTTP_CONNECT_TIMEOUT = 5
FISERV_HTTP_READ_TIMEOUT = 30
FISERV_HTTP_TIMEOUT = (FISERV_HTTP_CONNECT_TIMEOUT, FISERV_HTTP_READ_TIMEOUT)

# Códigos ITD que indican que el ticket no está en el lote actual del pinpad y
# por lo tanto ``processFinancialPurchaseVoidByTicket`` no puede completarse.
# Según la especificación Fiserv ITD v3.5 (sección ``processFinancialPurchaseVoidByTicket``)
# esto ocurre cuando se hizo cierre de lote entre la venta y el intento de anular;
# la recomendación del manual es ejecutar ``processFinancialPurchaseRefund`` en su lugar.
FISERV_ITD_RC_VOID_SHOULD_REFUND = ('109', '110')

# posResponseCode (Anexo 2) que indican que un void aceptado al inicio (RC=0) no
# encontró la transacción original al consultar el resultado en el pinpad. Esto
# ocurre cuando el lote del pinpad cerró entre la venta y la anulación: ITD
# acepta el processFinancialPurchaseVoidByTicket inicial (RC=0) pero la
# respuesta del Query trae posResponseCode 21/25 ("no existe original").
# Mismo remedio que con RC 109/110: re-ejecutar como processFinancialPurchaseRefund.
FISERV_POS_RC_VOID_NEEDS_REFUND_AFTER_QUERY = ('21', '25')

# Claves del payload que no deben salir en logs ni quedar legibles en el
# request guardado para auditoría.
FISERV_SENSITIVE_KEYS = ('SystemId',)


# ---------------------------------------------------------------------------
# Transacciones de base de datos
# ---------------------------------------------------------------------------
def fiserv_safe_commit(env):
    """
    Commit real, salvo durante tests: un commit dentro de una corrida de
    tests destruye los savepoints por-test de TransactionCase y aborta el
    resto de la suite.

    En producción el flujo contable DEBE commitear en dos puntos: al dejar
    registrada la transacción ANTES de hablar con ITD (si el proceso muere a
    mitad, el rastro del cobro existe igual) y al cerrar el resultado.

    🔴 **Un servidor levantado con ``--test-enable`` NO sirve para operar
    Fiserv.** El guard mira ``config['test_enable']``, que es global del
    proceso: en un server que atiende pedidos reales con esa opción puesta
    se saltean TODOS estos commits y el efecto es silencioso.
    ``PaymentProvider._fiserv_avisar_runtime_invalido`` avisa al arrancar.
    """
    if getattr(threading.current_thread(), 'testing', False) or _en_modo_test(env):
        return
    env.cr.commit()


def _en_modo_test(env):
    """
    ¿Estamos dentro de una corrida de tests?

    En 19.0 ``registry.in_test_mode()`` ya no existe: el modo test se
    implementa parcheando ``registry.cursor``. Lo que vale es la opción con la
    que corre el proceso: durante una corrida de tests no hay flujo productivo
    que necesite commitear.
    """
    en_test = getattr(env.registry, 'in_test_mode', None)
    if callable(en_test):
        return en_test()
    return bool(config.get('test_enable'))


# ---------------------------------------------------------------------------
# Datos sensibles
# ---------------------------------------------------------------------------
def fiserv_mask_payload(data):
    """
    Copia del payload con los identificadores del comercio enmascarados.

    El SystemId identifica al comercio ante ITD: no va a logs ni queda
    legible en ``fiserv_complete_request``, que lo ve cualquier contador.
    Se conservan los 2 últimos caracteres para poder distinguir ambientes.
    """
    if not isinstance(data, dict):
        return data
    masked = copy.deepcopy(data)
    for key in FISERV_SENSITIVE_KEYS:
        value = masked.get(key)
        if value not in (None, False, ''):
            text = str(value)
            masked[key] = '***' + text[-2:] if len(text) > 2 else '***'
    return masked


def fiserv_mask_payload_json(data):
    """El payload enmascarado, como JSON legible para ``fiserv_complete_request``."""
    import json
    return json.dumps(fiserv_mask_payload(data), indent=2, ensure_ascii=False)


def fiserv_is_transport_failure(response_json):
    """True si la respuesta es nuestra respuesta sintética de transporte."""
    return (
        isinstance(response_json, dict)
        and str(response_json.get('ResponseCode', '')).strip() == FISERV_RC_TRANSPORTE
    )


def fiserv_void_response_needs_refund_fallback(original_data, query_result):
    """
    Indica si la respuesta del Query a un void requiere fallback a refund.

    Args:
        original_data (dict): Payload original enviado a ITD.
        query_result (dict): Respuesta final del Query loop.

    Returns:
        bool: True solo si la operación inicial fue void (TicketNumber sin
        Amount) y el Query devolvió ``posResponseCode`` en
        ``FISERV_POS_RC_VOID_NEEDS_REFUND_AFTER_QUERY``.
    """
    if not original_data or not isinstance(query_result, dict):
        return False
    # Void puro: tiene TicketNumber pero no Amount. Refund tiene ambos; cobro
    # normal no tiene TicketNumber. Solo el void puro entra al fallback.
    if not original_data.get('TicketNumber') or original_data.get('Amount'):
        return False
    pos_code = query_result.get('PosResponseCode') or query_result.get('posResponseCode')
    if pos_code is None or pos_code == '':
        return False
    return str(pos_code).strip().upper() in FISERV_POS_RC_VOID_NEEDS_REFUND_AFTER_QUERY


def _fiserv_extract_itd_message_from_body(response_json):
    """
    Obtiene el texto descriptivo que envía ITD antes de aplicar la tabla genérica POSLink.

    Algunos entornos devuelven el detalle en Message/Description y ResponseCode=999; si
    pisamos siempre con FISERV_ITD_RESPONSE_CODE_MSG se pierde la causa real.
    """
    if not isinstance(response_json, dict):
        return ''
    for key in (
        'Message',
        'msg',
        'Description',
        'description',
        'ErrorMessage',
        'errorMessage',
        'ErrorDescription',
        'errorDescription',
        'Detail',
        'detail',
    ):
        val = response_json.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ''


def _fiserv_normalize_itd_http_response(response_json):
    """
    Normaliza el JSON devuelto por ITD: ResponseCode y TransactionId suelen venir como int;
    Odoo compara contra strings. Evita KeyError si aparece un código nuevo.
    """
    if not isinstance(response_json, dict):
        return response_json
    # Texto del host (si existe) tiene prioridad sobre la tabla de códigos
    itd_text = _fiserv_extract_itd_message_from_body(response_json)
    rc = response_json.get('ResponseCode')
    response_json['ResponseCode'] = str(rc).strip() if rc is not None else '999'
    tid = response_json.get('TransactionId')
    if tid is not None:
        response_json['TransactionId'] = str(tid).strip()
    stid = response_json.get('STransactionId')
    if stid is not None:
        response_json['STransactionId'] = str(stid).strip()
    code = response_json['ResponseCode']
    mapped = FISERV_ITD_RESPONSE_CODE_MSG.get(
        code,
        'Respuesta ITD (código %s)' % code,
    )
    response_json['msg'] = itd_text or mapped
    return response_json


def _fiserv_transport_response(msg):
    """Respuesta sintética de transporte (ver FISERV_RC_TRANSPORTE)."""
    return {
        'ResponseCode': FISERV_RC_TRANSPORTE,
        'TransactionId': '0',
        'STransactionId': '0',
        'msg': msg,
    }


def fiserv_itd_http_post(
    base_url_endpoint,
    path_suffix,
    data,
    log_label,
    extra_999_pos_warning=False,
):
    """
    POST JSON a ITD (processFinancialPurchase, Query, voidByTicket, etc.).

    Nunca levanta por transporte. Distingue dos cosas que antes se
    mezclaban bajo el mismo 999:

    - ITD CONTESTÓ y dijo que no (JSON con su ResponseCode, o un 4xx del
      servicio): se devuelve tal cual, normalizado.
    - NO HUBO RESPUESTA USABLE (timeout, conexión, 5xx, 408/429, 2xx que no
      es JSON): se devuelve ``FISERV_RC_TRANSPORTE``. El pedido pudo haber
      llegado a ITD y haber una operación viva en el pinpad; el llamador no
      puede tratarlo como rechazo.

    Returns:
        tuple: (base_url_endpoint, response_json normalizado).
    """
    base_url_endpoint = (base_url_endpoint or '').rstrip('/')
    endpoint = base_url_endpoint + path_suffix
    _logger.info('Fiserv %s request:\n%s', log_label, pprint.pformat(fiserv_mask_payload(data)))
    try:
        req = requests.post(
            endpoint,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=FISERV_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        _logger.warning('Fiserv %s: error de transporte contra %s: %s', log_label, endpoint, exc)
        return base_url_endpoint, _fiserv_transport_response(
            'Sin respuesta de ITD (%s): %s' % (type(exc).__name__, exc)
        )
    body_preview = (req.text or '')[:400]
    if req.status_code >= 500 or req.status_code in FISERV_HTTP_TRANSPORTE:
        _logger.error(
            'Fiserv %s HTTP %s URL=%s cuerpo (recorte): %s',
            log_label, req.status_code, endpoint, body_preview,
        )
        return base_url_endpoint, _fiserv_transport_response(
            'ITD respondió HTTP %s: la operación pudo haber llegado igual.' % req.status_code
        )
    if not (200 <= req.status_code < 300):
        _logger.error(
            'Fiserv %s HTTP %s URL=%s cuerpo (recorte): %s',
            log_label, req.status_code, endpoint, body_preview,
        )
        err = {
            'ResponseCode': '999',
            'TransactionId': '0',
            'STransactionId': '0',
            'msg': (
                'ITD rechazó el pedido con HTTP %s. Compruebe la URL del proveedor '
                'Fiserv y los datos enviados. Recorte de respuesta: %s'
            ) % (req.status_code, body_preview),
        }
        return base_url_endpoint, _fiserv_normalize_itd_http_response(err)
    try:
        response_json = req.json()
    except ValueError:
        _logger.error(
            'Fiserv %s: respuesta no JSON desde %s: %s', log_label, endpoint, body_preview,
        )
        return base_url_endpoint, _fiserv_transport_response(
            'La respuesta de ITD no es JSON válido (¿URL correcta?). Recorte: %s' % body_preview
        )
    if not isinstance(response_json, dict):
        return base_url_endpoint, _fiserv_transport_response(
            'La respuesta de ITD no es un objeto JSON. Recorte: %s' % body_preview
        )
    _fiserv_normalize_itd_http_response(response_json)
    _logger.info('Fiserv %s response:\n%s', log_label, pprint.pformat(response_json))
    if (
        extra_999_pos_warning
        and response_json.get('ResponseCode') == '999'
        and str(response_json.get('TransactionId', '0') or '0').strip() in ('0', '')
    ):
        _logger.warning(
            'Fiserv ITD rechazó el inicio (999, TransactionId=0). Revise con el proveedor: '
            'URL, PosID %s, Branch %s, moneda/campos obligatorios. Mensaje: %s',
            data.get('PosID'),
            data.get('Branch'),
            response_json.get('msg'),
        )
    return base_url_endpoint, response_json


def _fiserv_card_data_ready_for_confirm(query_result):
    """
    Indica si la consulta ITD trae BIN/adquirente/emisor útiles para confirmar la compra.

    ITD suele devolver Acquirer/Issuer numéricos distintos de 0 cuando la tarjeta ya fue leída
    (ResponseCode 12). Sin esto no se debe llamar a processConfirmFinancialPurchase.
    """
    try:
        acq = int(str(query_result.get('Acquirer', 0)).strip() or 0)
        iss = int(str(query_result.get('Issuer', 0)).strip() or 0)
    except (TypeError, ValueError):
        return False
    return acq != 0 and iss != 0


def _fiserv_resolve_quota_for_confirm(purchase_data, query_result):
    """
    Cuotas finales para confirm: prioriza lo devuelto por Query (Quota/Quotas), luego el cobro inicial.
    """
    for key in ('Quota', 'Quotas'):
        val = query_result.get(key)
        if val is not None and val != '':
            try:
                n = int(str(val).strip())
                if n >= 1:
                    return n
            except (TypeError, ValueError):
                continue
    for key in ('Installments', 'Quotas'):
        val = purchase_data.get(key)
        if val is not None and val != '':
            try:
                n = int(str(val).strip())
                if n >= 1:
                    return n
            except (TypeError, ValueError):
                continue
    return 1


def _fiserv_build_confirm_financial_purchase_payload(
    original_purchase_data,
    query_result,
    transaction_id,
    driver,
):
    """
    Arma el cuerpo de processConfirmFinancialPurchase (POSLink / ITD) tras RC=12.

    Debe alinearse con el payload inicial (montos en centavos como string) y con los datos
    de tarjeta devueltos por processFinancialPurchaseQuery.

    ``driver`` es el modelo que expone ``_fiserv_timestamp()`` (hoy
    ``payment.provider``).
    """
    quota_value = _fiserv_resolve_quota_for_confirm(original_purchase_data, query_result)
    try:
        tax_refund = int(original_purchase_data.get('TaxRefund', 0))
    except (TypeError, ValueError):
        tax_refund = 0
    plan_raw = original_purchase_data.get('Plan', 0)
    try:
        plan_val = int(plan_raw)
    except (TypeError, ValueError):
        plan_val = 0
    return {
        'PosID': original_purchase_data['PosID'],
        'SystemId': original_purchase_data['SystemId'],
        'Branch': original_purchase_data['Branch'],
        'ClientAppId': original_purchase_data['ClientAppId'],
        'UserId': str(original_purchase_data['UserId']),
        'TransactionDateTimeyyyyMMddHHmmssSSS': driver._fiserv_timestamp(),
        'TransactionId': str(transaction_id).strip(),
        'Amount': str(original_purchase_data.get('Amount', '0')),
        'Quotas': quota_value,
        'Plan': plan_val,
        'Currency': str(original_purchase_data.get('Currency', '858')),
        'TaxRefund': tax_refund,
        'TaxableAmount': str(original_purchase_data.get('TaxableAmount', '0')),
        'InvoiceAmount': str(original_purchase_data.get('InvoiceAmount', '0')),
        'InvoiceNumber': str(original_purchase_data.get('InvoiceNumber', '1')),
        'TaxAmount': '0',
        'TipAmount': '0',
        'CardAccountType': '0',
        'Acquirer': query_result.get('Acquirer', ''),
        'Issuer': query_result.get('Issuer', ''),
        'CardNumber': query_result.get('CardNumber', ''),
    }
