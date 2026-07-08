# -*- coding: utf-8 -*-
"""
Utilidades y constantes compartidas de la integración Fiserv ITD.

Este módulo contiene funciones puras (sin modelos Odoo) que usan tanto el flujo POS
(pos.payment.method) como el flujo contable (payment.provider / account.payment).
Viven en el core para evitar dependencias cruzadas entre los módulos backend y POS.
"""

import logging
import pprint

import requests

from odoo import _, api, SUPERUSER_ID

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
    Odoo y el POS comparan contra strings. Evita KeyError si aparece un código nuevo.
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


def fiserv_itd_http_post(
    base_url_endpoint,
    path_suffix,
    data,
    log_label,
    extra_999_pos_warning=False,
):
    """
    POST JSON genérico a ITD (processFinancialPurchase, voidByTicket, etc.).

    Centraliza validación HTTP, parseo y normalización para ``pos.payment.method`` y
    ``payment.provider`` (cobro contable sin configurar POS).

    Args:
        base_url_endpoint (str): URL base sin barra final.
        path_suffix (str): Ruta del recurso (p. ej. ``/processFinancialPurchase``).
        data (dict): Cuerpo JSON.
        log_label (str): Nombre para logs (p. ej. ``processFinancialPurchase``).
        extra_999_pos_warning (bool): Si True, log adicional cuando RC=999 y TransactionId=0.

    Returns:
        tuple: (base_url_endpoint, response_json normalizado).
    """
    base_url_endpoint = (base_url_endpoint or '').rstrip('/')
    endpoint = base_url_endpoint + path_suffix
    req = requests.post(
        endpoint,
        json=data,
        headers={'Content-Type': 'application/json'},
        timeout=30,
    )
    is_void = 'VoidByTicket' in path_suffix
    if not (200 <= req.status_code < 300):
        body_preview = (req.text or '')[:2000]
        _logger.error(
            'Fiserv %s HTTP %s URL=%s cuerpo (recorte): %s',
            log_label,
            req.status_code,
            endpoint,
            body_preview,
        )
        err = {
            'ResponseCode': '999',
            'TransactionId': '0',
            'STransactionId': '0',
            'msg': (
                _(
                    'ITD (anulación) respondió HTTP %(status)s. Recorte: %(body)s'
                )
                if is_void
                else _(
                    'ITD respondió HTTP %(status)s. Compruebe la URL del proveedor Fiserv, '
                    'certificados y conectividad. Recorte de respuesta: %(body)s'
                )
            )
            % {'status': req.status_code, 'body': (req.text or '')[:400]},
        }
        _fiserv_normalize_itd_http_response(err)
        return base_url_endpoint, err
    try:
        response_json = req.json()
    except ValueError:
        body_preview = (req.text or '')[:2000]
        _logger.error(
            'Fiserv %s: respuesta no JSON desde %s: %s',
            log_label,
            endpoint,
            body_preview,
        )
        err = {
            'ResponseCode': '999',
            'TransactionId': '0',
            'STransactionId': '0',
            'msg': (
                _('ITD (anulación) devolvió respuesta no JSON. Recorte: %(body)s')
                if is_void
                else _(
                    'La respuesta de ITD no es JSON válido (¿URL apunta al servicio correcto?). '
                    'Recorte: %(body)s'
                )
            )
            % {'body': (req.text or '')[:400]},
        }
        _fiserv_normalize_itd_http_response(err)
        return base_url_endpoint, err
    _fiserv_normalize_itd_http_response(response_json)
    _logger.info('%s Response:\n%s', log_label, pprint.pformat(response_json))
    if (
        extra_999_pos_warning
        and str(response_json.get('ResponseCode', '')).strip() == '999'
        and str(response_json.get('TransactionId', '0') or '0').strip() in ('0', '')
    ):
        _logger.warning(
            'Fiserv ITD rechazó el inicio (999, TransactionId=0). Revise con el proveedor: '
            'URL, PosID %s, SystemId %s, Branch %s, moneda/campos obligatorios. Mensaje: %s',
            data.get('PosID'),
            data.get('SystemId'),
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
    payment_method,
):
    """
    Arma el cuerpo de processConfirmFinancialPurchase (POSLink / ITD) tras RC=12.

    Debe alinearse con el payload inicial (montos en centavos como string) y con los datos
    de tarjeta devueltos por processFinancialPurchaseQuery.

    ``payment_method`` es el driver que expone ``get_formatted_timestamp()`` (puede ser
    un ``pos.payment.method`` o un ``payment.provider``).
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
        'TransactionDateTimeyyyyMMddHHmmssSSS': payment_method.get_formatted_timestamp(),
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


def _fiserv_http_post_confirm_financial_purchase(base_url_endpoint, confirm_data):
    """
    POST a processConfirmFinancialPurchase; normaliza ResponseCode/msg como el resto de ITD.
    """
    endpoint = (base_url_endpoint or '').rstrip('/') + '/processConfirmFinancialPurchase'
    req = requests.post(
        endpoint,
        json=confirm_data,
        headers={'Content-Type': 'application/json'},
        timeout=30,
    )
    response_json = req.json()
    _fiserv_normalize_itd_http_response(response_json)
    _logger.info('processConfirmFinancialPurchase Response:\n%s', pprint.pformat(response_json))
    return response_json


def fiserv_itd_background_worker_account_payment(
    pool,
    provider_id,
    run_uid,
    data,
    bus_channel_name,
    id_config,
    transaction_id,
    base_url_endpoint,
    pos_session_id,
    account_payment_id=None,
):
    """
    Hilo ITD cuando el cobro contable usa ``payment.provider`` (sin ``pos.payment.method``).

    Usa el proveedor como driver del bucle Query (misma API HTTP que el TPV; no requiere
    diario vinculado al POS). El bucle Query vive en ``payment.transaction`` para que
    core no dependa del módulo POS.
    """
    effective_uid = run_uid if run_uid is not None else SUPERUSER_ID
    tid_norm = str(transaction_id).strip()
    with pool.cursor() as new_cr:
        env = api.Environment(new_cr, effective_uid, {})
        try:
            prov = env['payment.provider'].browse(provider_id)
            query_data = {
                'PosID': data['PosID'],
                'SystemId': data['SystemId'],
                'Branch': data['Branch'],
                'ClientAppId': data['ClientAppId'],
                'UserId': data['UserId'],
                'TransactionDateTimeyyyyMMddHHmmssSSS': prov.get_formatted_timestamp(),
                'TransactionId': transaction_id,
            }
            result = env['payment.transaction'].fiserv_run_purchase_query_loop(
                prov,
                query_data,
                base_url_endpoint,
                transaction_id,
                pos_session_id,
                original_purchase_data=data,
            )

            # Fallback void→refund post-Query: ITD acepta el void inicial (RC=0)
            # y luego en el Query devuelve posResponseCode 21/25 ("no existe
            # original") por cierre de lote. Mismo remedio que para RC=109/110:
            # reejecutar como refund. Aquí el swap corre en línea: el resultado
            # final que se persiste pasa a ser el del refund.
            if account_payment_id and fiserv_void_response_needs_refund_fallback(data, result):
                _logger.info(
                    'Fiserv void→refund (post-Query): posResponseCode %s en void '
                    'tx=%s, lanzando refund automático',
                    result.get('PosResponseCode') or result.get('posResponseCode'),
                    tid_norm,
                )
                swap = prov._fiserv_run_void_to_refund_swap_in_thread(
                    account_payment_id, data, base_url_endpoint, pos_session_id,
                )
                if swap:
                    new_tid, data, result = swap
                    transaction_id = new_tid
                    tid_norm = str(new_tid).strip()
                    _logger.info(
                        'Fiserv void→refund (post-Query): swap ejecutado, nueva tx ITD=%s',
                        tid_norm,
                    )
            try:
                env['payment.transaction'].fiserv_persist_after_query_generic(
                    tid_norm,
                    result,
                    pos_session_id,
                    account_payment_id=account_payment_id,
                    # Tras el swap void→refund, ``data`` es el request del refund
                    # realmente enviado; es lo que corresponde auditar.
                    pos_data=data,
                )
            except Exception as err_upd:
                _logger.error(
                    'Error al actualizar transacción en segundo plano (provider): %s',
                    str(err_upd),
                )

            result.update({
                'id_config': id_config,
                'origin_transaction_id': transaction_id,
            })
            send_bus = not account_payment_id
            if send_bus and bus_channel_name:
                try:
                    env['bus.bus'].sudo()._sendone(
                        bus_channel_name, 'FISERV_LATEST_RESPONSE', result
                    )
                except Exception as bus_err:
                    _logger.error('Error al enviar mensaje bus: %s', str(bus_err))

            if account_payment_id:
                pay = env['account.payment'].browse(account_payment_id)
                bus_posted = False
                bus_message = ''
                if pay.exists():
                    tx = env['payment.transaction'].sudo().search(
                        [('fiserv_transaction_id', '=', tid_norm)],
                        limit=1,
                    )
                    if tx:
                        tx.write(
                            {
                                'account_payment_id': account_payment_id,
                                'transaction_origin': 'account_payment',
                            }
                        )
                    vals_pending = {'fiserv_async_terminal_pending': False}
                    if tx and 'payment_transaction_id' in pay._fields:
                        vals_pending['payment_transaction_id'] = tx.id
                    pay.sudo().write(vals_pending)
                    state = env['payment.transaction']._get_transaction_state_with_pos_response(
                        str(result.get('ResponseCode', '999')).strip(),
                        result,
                    )
                    new_cr.commit()
                    pay = env['account.payment'].browse(account_payment_id)
                    if state == 'done':
                        # Nuevo flujo: NO se auto-postea. El pago queda en draft con
                        # la transacción aprobada y el botón «Confirmar» del form es
                        # el que registra contablemente (control manual del usuario).
                        bus_posted = False
                        bus_message = _(
                            'El cobro en el terminal fue aprobado. Pulse «Confirmar» '
                            'para registrar el pago contablemente.'
                        )
                        pay.message_post(
                            body=_(
                                'Fiserv ITD: cobro aprobado por el pinpad. '
                                'Pulse «Confirmar» para postear el pago contable.'
                            )
                        )
                    else:
                        if pay.payment_type == 'outbound':
                            body_txt = _(
                                'Fiserv ITD (devolución): la anulación no quedó aprobada en el terminal '
                                '(estado %(st)s). %(msg)s'
                            ) % {'st': state, 'msg': result.get('msg') or ''}
                        else:
                            body_txt = _(
                                'Fiserv ITD: el cobro no quedó aprobado en el terminal '
                                '(estado %(st)s). %(msg)s'
                            ) % {'st': state, 'msg': result.get('msg') or ''}
                        pay.message_post(body=body_txt)
                        bus_message = body_txt
                    env['account.payment']._fiserv_bus_notify_after_terminal(
                        effective_uid,
                        account_payment_id,
                        bus_posted,
                        bus_message,
                    )
            new_cr.commit()
        except Exception:
            _logger.exception(
                'Fiserv fiserv_itd_background_worker_account_payment falló '
                '(account_payment_id=%s, tx=%s)',
                account_payment_id,
                tid_norm,
            )
            new_cr.rollback()
            if account_payment_id and effective_uid:
                try:
                    with pool.cursor() as cr_bus:
                        env_bus = api.Environment(cr_bus, effective_uid, {})
                        env_bus['account.payment']._fiserv_bus_notify_after_terminal(
                            effective_uid,
                            account_payment_id,
                            False,
                            _(
                                'Error al procesar la respuesta del terminal Fiserv. '
                                'Revise el registro de pago y el chatter.'
                            ),
                        )
                        cr_bus.commit()
                except Exception:
                    _logger.exception('Fiserv: notificación bus tras error en hilo (provider)')
        finally:
            if account_payment_id:
                with pool.cursor() as cr2:
                    env2 = api.Environment(cr2, effective_uid, {})
                    p2 = env2['account.payment'].browse(account_payment_id)
                    if p2.exists() and p2.fiserv_async_terminal_pending:
                        p2.sudo().write({'fiserv_async_terminal_pending': False})
                    cr2.commit()
