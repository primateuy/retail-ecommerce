# -*- coding: utf-8 -*-
"""
Extensión del modelo pos.payment.method para soporte de promociones OCA

Este módulo agrega funcionalidad para:
- Procesar confirmación de transacciones con valores modificados (promociones)
- Obtener información de promociones basadas en datos de tarjeta
"""

import pprint
import logging
import requests
import threading
from time import sleep

from odoo import fields, models, api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def parse_applied_loyalty_ids_from_payload(data):
    """
    Lee IDs de programas de lealtad desde el dict enviado al pinpad (si el conector los conserva).
    """
    if not data or not isinstance(data, dict):
        _logger.info(
            "OCA_PROMOS_PAYLOAD: sin dict data o vacío → ids de lealtad desde pinpad = []"
        )
        return []
    raw = data.get("OcaAppliedLoyaltyProgramIds") or data.get(
        "oca_applied_loyalty_program_ids"
    )
    if raw in (None, False, ""):
        _logger.info(
            "OCA_PROMOS_PAYLOAD: claves OcaAppliedLoyaltyProgramIds / "
            "oca_applied_loyalty_program_ids vacías o ausentes"
        )
        return []
    if isinstance(raw, (list, tuple, set)):
        out = []
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        _logger.info(
            "OCA_PROMOS_PAYLOAD: lealtad desde pinpad (lista) | raw=%s | parseados=%s",
            raw,
            out,
        )
        return out
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    _logger.info(
        "OCA_PROMOS_PAYLOAD: lealtad desde pinpad (string/CSV) | raw=%r | parseados=%s",
        raw,
        out,
    )
    return out


def get_applied_loyalty_program_ids_for_oca_thread(env, pos_session_id, data):
    """
    IDs de loyalty.program aplicados al carrito que se está cobrando: snapshot en pos.session
    (guardado por el POS web antes de pagar), payload opcional, y líneas del borrador en servidor.
    """
    Promo = env["payment.method.promotion"]
    from_payload = set(parse_applied_loyalty_ids_from_payload(data or {}))
    from_session = set()
    from_order_lines = set()

    session = env["pos.session"].sudo().browse(int(pos_session_id))
    if session.exists():
        csv_val = session.oca_applied_loyalty_program_ids
        _logger.info(
            "OCA_PROMOS_MERGE: pos.session | session_id=%s | oca_applied_loyalty_program_ids=%r",
            pos_session_id,
            csv_val,
        )
        if csv_val:
            for part in csv_val.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    from_session.add(int(part))
                except ValueError:
                    _logger.warning(
                        "OCA_PROMOS_MERGE: token no numérico en CSV sesión | part=%r",
                        part,
                    )
    else:
        _logger.warning(
            "OCA_PROMOS_MERGE: pos.session id=%s no existe (sudo browse)",
            pos_session_id,
        )

    order = env["pos.order"].search(
        [
            ("session_id", "=", int(pos_session_id)),
            ("state", "=", "draft"),
        ],
        order="id desc",
        limit=1,
    )
    if order:
        from_order_lines = set(
            Promo.collect_applied_loyalty_program_ids_from_pos_order(order)
        )
        _logger.info(
            "OCA_PROMOS_MERGE: borrador pos.order | order_id=%s | name=%s | "
            "loyalty.program ids desde líneas=%s",
            order.id,
            order.name,
            sorted(from_order_lines),
        )
    else:
        _logger.info(
            "OCA_PROMOS_MERGE: no hay pos.order draft para session_id=%s",
            pos_session_id,
        )

    seen = set(from_payload) | from_session | from_order_lines
    _logger.info(
        "OCA_PROMOS_MERGE: resumen | session_id=%s | desde_pinpad=%s | desde_sesión=%s | "
        "desde_borrador=%s | UNIÓN_FINAL=%s",
        pos_session_id,
        sorted(from_payload),
        sorted(from_session),
        sorted(from_order_lines),
        sorted(seen),
    )
    return sorted(seen)


class PosPaymentMethod(models.Model):
    """
    Extensión del modelo pos.payment.method para promociones OCA
    
    Nota: El producto de descuento ahora se obtiene de la configuración
    de promociones (payment.method.promotion), no desde este modelo.
    """
    _inherit = 'pos.payment.method'

    def processFinancialPurchase(self, data, pos_session_id, account_payment_id=None):
        """
        Extiende processFinancialPurchase para verificar promociones activas
        y agregar NeedToReadCard si es necesario.

        Si hay promociones activas configuradas para este método de pago,
        se agrega NeedToReadCard: True para que el POS lea los datos de la tarjeta
        desde el inicio y se pueda procesar la promoción correctamente.

        IMPORTANTE: Cuando hay promociones activas, este método NO llama al método base
        para evitar que se inicie el hilo de procesamiento en segundo plano dos veces.
        En su lugar, implementa la lógica completa aquí.

        Args:
            data (dict): Datos de la transacción a enviar al POS
            pos_session_id (int): ID de la sesión POS
            account_payment_id (int|None): Propagado a la cadena (p. ej. odoo_pos_fiserv + account.payment).

        Returns:
            dict: Respuesta del POS
        """
        self.ensure_one()
        
        # Verificar si hay promociones activas para este método de pago
        # Buscar promociones que puedan aplicarse a este método de pago
        has_active_promotions = False
        
        try:
            # Buscar promociones activas que puedan aplicarse a este método de pago
            # Verificar si hay promociones configuradas para este método de pago o para OCA en general
            provider_code = 'oca' if self.use_payment_terminal == 'oca' else None
            
            # Buscar promociones activas solo por proveedor (aplica a todos los métodos con ese proveedor)
            if provider_code:
                domain = [
                    ('active', '=', True),
                    ('payment_provider_id.code', '=', provider_code),
                    '|',
                    ('company_id', '=', False),
                    ('company_id', '=', self.env.company.id),
                ]
                promotions = self.env['payment.method.promotion'].search(domain, limit=1)
                if promotions:
                    has_active_promotions = True
                    _logger.info('Promociones activas encontradas para proveedor %s', provider_code)
            
            # Si hay promociones activas, agregar NeedToReadCard para que el POS lea la tarjeta
            if has_active_promotions:
                if 'NeedToReadCard' not in data:
                    data['NeedToReadCard'] = True
                    _logger.info('Agregando NeedToReadCard: True a processFinancialPurchase porque hay promociones activas')
                elif not data.get('NeedToReadCard'):
                    data['NeedToReadCard'] = True
                    _logger.info('Forzando NeedToReadCard: True a processFinancialPurchase porque hay promociones activas')
        except Exception as e:
            _logger.warning('Error al verificar promociones activas en processFinancialPurchase: %s', str(e))
            # Continuar sin agregar NeedToReadCard si hay error
        
        # Si hay promociones activas, implementar la lógica completa aquí para evitar doble procesamiento
        if has_active_promotions and data.get('NeedToReadCard'):
            # Llamar directamente al endpoint sin pasar por el método base
            # para evitar que se inicie el hilo de procesamiento en segundo plano dos veces
            _logger.info('Metodo processFinancialPurchase %s', pprint.pformat(data))
            
            # Log detallado de los campos enviados
            _logger.info('OCA Data Fields Check:')
            _logger.info('  PosID: %s', data.get('PosID'))
            _logger.info('  SystemId: %s', data.get('SystemId'))
            _logger.info('  Branch: %s', data.get('Branch'))
            _logger.info('  ClientAppId: %s', data.get('ClientAppId'))
            _logger.info('  UserId: %s', data.get('UserId'))
            _logger.info('  Amount: %s', data.get('Amount'))
            _logger.info('  Currency: %s', data.get('Currency'))
            _logger.info('  InvoiceNumber: %s', data.get('InvoiceNumber'))
            _logger.info('  TransactionDateTimeyyyyMMddHHmmssSSS: %s', data.get('TransactionDateTimeyyyyMMddHHmmssSSS'))
            _logger.info('  Installments: %s | Quotas: %s', data.get('Installments'), data.get('Quotas'))
            _logger.info(
                'OCA_PROMOS processFinancialPurchase: OcaAppliedLoyaltyProgramIds en payload (si el conector lo reenvía)=%r',
                data.get('OcaAppliedLoyaltyProgramIds'),
            )
            
            base_url_endpoint = self.sudo().url_webservice
            endpoint = base_url_endpoint + '/processFinancialPurchase'
            headers = {
                'Content-Type': 'application/json',
            }
            
            # Enviar solicitud al POS
            req = requests.post(endpoint, json=data, headers=headers, timeout=30)
            response_json = req.json()
            response_json['ResponseCode'] = str(response_json['ResponseCode'])
            
            response_code_msg = {
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
            
            response_json['msg'] = response_code_msg.get(response_json['ResponseCode'], 'Código desconocido')
            
            _logger.info('processFinancialPurchase Response:\n%s', pprint.pformat(response_json))
            
            # Obtener información de la sesión POS
            pos_session_sudo = self.env["pos.session"].sudo().browse(pos_session_id)
            bus_channel_name = pos_session_sudo._get_bus_channel_name()
            id_config = pos_session_sudo.config_id.id
            
            # Almacenar la transacción en payment.transaction SOLO cuando recibimos respuesta del POS
            # PERO solo si la respuesta es exitosa y tenemos información completa
            if response_json['ResponseCode'] == '0':
                # Solo almacenar la transacción cuando tengamos información completa
                # La información completa llega después del procesamiento en segundo plano
                pass
            else:
                # Para respuestas de error, almacenar inmediatamente
                self._store_oca_transaction(data, response_json, pos_session_id)
            
            # Iniciar el procesamiento en segundo plano SOLO UNA VEZ cuando hay promociones activas
            # El POS puede responder con '0' (transacción creada, esperando tarjeta),
            # '10' (esperando tarjeta) o '12' (tarjeta leída)
            # En todos estos casos, necesitamos iniciar el procesamiento en segundo plano
            response_code = response_json.get('ResponseCode', '')
            if response_code in ('0', '10', '12'):
                transaction_id = response_json.get('TransactionId')
                if transaction_id:
                    _logger.info('Iniciando procesamiento en segundo plano para promociones con ResponseCode=%s, TransactionId=%s', 
                               response_code, transaction_id)
                    # Iniciar hilo para procesamiento en segundo plano
                    # Este hilo esperará a que se lea la tarjeta y procesará la promoción solo si el BIN coincide
                    threading.Thread(target=self._procesar_en_segundo_plano, 
                                   args=(data, bus_channel_name, id_config, transaction_id, base_url_endpoint, pos_session_id)).start()
                else:
                    _logger.warning('No se pudo iniciar procesamiento en segundo plano: TransactionId no disponible en respuesta con ResponseCode=%s', 
                                  response_code)
            
            return response_json
        else:
            # Si no hay promociones activas, llamar al método base normalmente
            return super(PosPaymentMethod, self).processFinancialPurchase(
                data, pos_session_id, account_payment_id=account_payment_id
            )

    def _call_process_financial_purchase_direct(self, data):
        """
        Llama directamente al endpoint processFinancialPurchase sin iniciar hilo de procesamiento
        
        Este método se usa cuando ya estamos dentro de un hilo de procesamiento
        y necesitamos reenviar la transacción con monto modificado.
        
        Args:
            data (dict): Datos de la transacción a enviar al POS
            
        Returns:
            dict: Respuesta del POS
        """
        self.ensure_one()
        import requests
        
        _logger.info('Llamada directa a processFinancialPurchase (sin hilo): %s', pprint.pformat(data))
        
        base_url_endpoint = self.sudo().url_webservice
        endpoint = base_url_endpoint + '/processFinancialPurchase'
        headers = {
            'Content-Type': 'application/json',
        }
        
        # Enviar solicitud al POS
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        response_json['ResponseCode'] = str(response_json['ResponseCode'])
        
        response_code_msg = {
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
        
        response_json['msg'] = response_code_msg.get(response_json['ResponseCode'], 'Código desconocido')
        
        _logger.info('Respuesta de llamada directa processFinancialPurchase: %s', pprint.pformat(response_json))
        
        return response_json

    def processConfirmFinancialPurchase(self, data, pos_session_id):
        """
        Confirma una transacción financiera con valores modificados
        después de obtener datos de la tarjeta (promociones)
        
        Según documentación POSLink v135, sección 3.2:
        - Se llama después de obtener datos de tarjeta (ResponseCode = 12)
        - Permite modificar monto, cuotas, plan, etc.
        - Confirma los valores finales para procesamiento
        
        Args:
            data (dict): Datos de confirmación con valores finales
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            dict: Respuesta del POS
        """
        self.ensure_one()
        _logger.info('Metodo processConfirmFinancialPurchase %s', pprint.pformat(data))
        
        # Log detallado de los campos enviados
        _logger.info('OCA Confirm Data Fields Check:')
        _logger.info('  TransactionId: %s', data.get('TransactionId'))
        _logger.info('  Amount: %s', data.get('Amount'))
        _logger.info('  Quotas: %s', data.get('Quotas'))
        _logger.info('  Plan: %s', data.get('Plan'))
        _logger.info('  TaxableAmount: %s', data.get('TaxableAmount'))
        _logger.info('  InvoiceAmount: %s', data.get('InvoiceAmount'))
        
        base_url_endpoint = self.sudo().url_webservice
        endpoint = base_url_endpoint + '/processConfirmFinancialPurchase'
        headers = {
            'Content-Type': 'application/json',
        }
        
        # Enviar solicitud al POS
        try:
            _logger.info('Enviando datos a processConfirmFinancialPurchase: %s', pprint.pformat(data))
            _logger.info('Endpoint: %s', endpoint)
            req = requests.post(endpoint, json=data, headers=headers, timeout=30)
            
            # Log de respuesta HTTP
            _logger.info('Respuesta HTTP - Status Code: %s, Headers: %s', req.status_code, dict(req.headers))
            _logger.info('Respuesta HTTP - Text (primeros 500 chars): %s', req.text[:500])
            
            # Verificar el código de estado HTTP
            if req.status_code != 200:
                _logger.error('Error HTTP al llamar a processConfirmFinancialPurchase: %s - %s', req.status_code, req.text)
                response_json = {
                    'ResponseCode': '999',
                    'msg': f'Error HTTP {req.status_code}: {req.text[:200]}'
                }
            else:
                # Intentar parsear JSON
                try:
                    if not req.text or req.text.strip() == '':
                        _logger.error('Respuesta vacía del POS para processConfirmFinancialPurchase')
                        response_json = {
                            'ResponseCode': '999',
                            'msg': 'Respuesta vacía del POS'
                        }
                    else:
                        response_json = req.json()
                        _logger.info('JSON parseado correctamente: %s', pprint.pformat(response_json))
                        
                        # Verificar que response_json no esté vacío
                        if not response_json or response_json == {}:
                            _logger.error('Respuesta JSON vacía del POS para processConfirmFinancialPurchase')
                            response_json = {
                                'ResponseCode': '999',
                                'msg': 'Respuesta JSON vacía del POS'
                            }
                        # Asegurar que ResponseCode existe y es string
                        elif 'ResponseCode' in response_json:
                            response_json['ResponseCode'] = str(response_json['ResponseCode'])
                        else:
                            _logger.error('Respuesta de processConfirmFinancialPurchase no contiene ResponseCode: %s', response_json)
                            response_json['ResponseCode'] = '999'
                            response_json['msg'] = 'Respuesta inválida del POS - falta ResponseCode'
                except ValueError as json_error:
                    _logger.error('Error al parsear JSON de respuesta: %s - Text: %s', str(json_error), req.text[:500])
                    response_json = {
                        'ResponseCode': '999',
                        'msg': f'Error al parsear respuesta JSON: {str(json_error)}'
                    }
        except requests.exceptions.RequestException as e:
            _logger.error('Error de conexión al llamar a processConfirmFinancialPurchase: %s', str(e))
            response_json = {
                'ResponseCode': '999',
                'msg': f'Error al comunicarse con el POS: {str(e)}'
            }
        except Exception as e:
            _logger.error('Error inesperado al llamar a processConfirmFinancialPurchase: %s', str(e))
            import traceback
            _logger.error('Traceback: %s', traceback.format_exc())
            response_json = {
                'ResponseCode': '999',
                'msg': f'Error inesperado: {str(e)}'
            }
        
        # Mismos códigos de respuesta que processFinancialPurchase
        response_code_msg = {
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
        
        response_json['msg'] = response_code_msg.get(response_json['ResponseCode'], 'Código desconocido')
        
        _logger.info('processConfirmFinancialPurchase Response:\n%s', pprint.pformat(response_json))
        
        return response_json

    def _procesar_en_segundo_plano(
        self,
        data,
        bus_channel_name,
        id_config,
        transaction_id,
        base_url_endpoint,
        pos_session_id,
        account_payment_id=None,
        user_id=None,
    ):
        """
        Extiende el método base para procesar promociones automáticamente desde el backend
        cuando se recibe ResponseCode = 12 con datos de tarjeta.

        Para la POC, todo el procesamiento se hace en el backend para evitar problemas
        de sincronización con el frontend.

        Args extra (compat odoo_pos_fiserv): account_payment_id, user_id — en terminal Fiserv
        se delega al _procesar_en_segundo_plano de Fiserv (mismo hilo que processFinancialPurchase).
        """
        if self.use_payment_terminal == 'fiserv':
            return super(PosPaymentMethod, self)._procesar_en_segundo_plano(
                data,
                bus_channel_name,
                id_config,
                transaction_id,
                base_url_endpoint,
                pos_session_id,
                account_payment_id=account_payment_id,
                user_id=user_id,
            )
        # Guardar el ID del payment method antes de crear el nuevo cursor
        payment_method_id = self.id
        
        # Nuevo cursor y entorno para evitar problemas de ORM compartido
        with self.pool.cursor() as new_cr:
            env = api.Environment(new_cr, SUPERUSER_ID, {})
            result = {}
            promotion_processed = False  # Flag para evitar procesar múltiples veces
            saved_promotion_info = None  # Variable para preservar promotion_info

            def _get_quota_value():
                """
                Cuotas para processConfirmFinancialPurchase: nunca 0 (OCA puede devolver EXCEDE CUOTAS).

                Se prioriza Quota/Quotas del resultado de consulta; luego Installments del cobro inicial;
                se ignoran valores < 1.
                """
                candidates = []
                for key in ('Quota', 'Quotas'):
                    val = result.get(key)
                    if val is not None and val != '':
                        candidates.append(val)
                for key in ('Installments', 'Quotas'):
                    val = data.get(key)
                    if val is not None and val != '':
                        candidates.append(val)
                for raw in candidates:
                    try:
                        n = int(raw)
                    except (TypeError, ValueError):
                        continue
                    if n >= 1:
                        return n
                return 1

            query_data = {
                "PosID": data['PosID'],
                "SystemId": data['SystemId'],
                "Branch": data['Branch'],
                "ClientAppId": data['ClientAppId'],
                "UserId": data['UserId'],
                "TransactionDateTimeyyyyMMddHHmmssSSS": env['pos.payment.method'].get_formatted_timestamp(),
                "TransactionId": transaction_id,
            }

            while True:
                sleep(4)
                _logger.info('>>>Intento Promociones>>>')
                try:
                    result = env['pos.payment.method'].processFinancialPurchaseQuery(query_data, base_url_endpoint)
                    _logger.info('Result Promociones: %s', pprint.pformat(result))

                    response_code = result['ResponseCode']
                    rt = result['RemainingExpirationTime'] if 'RemainingExpirationTime' in result else False
                    
                    # NUEVO: Procesar promoción automáticamente cuando se recibe ResponseCode = 12 con datos de tarjeta
                    # Solo procesar una vez, incluso si hay errores
                    # IMPORTANTE: Verificar que Acquirer e Issuer sean válidos (no 0) y que no se haya procesado ya
                    if response_code == '12' and result.get('Acquirer') and int(result.get('Acquirer', 0)) != 0 and result.get('Issuer') and int(result.get('Issuer', 0)) != 0 and not promotion_processed:
                            _logger.info('Procesando promoción automáticamente desde backend - Acquirer: %s, Issuer: %s', 
                                       result.get('Acquirer'), result.get('Issuer'))
                            
                            try:
                                # Obtener el método de pago
                                payment_method = env['pos.payment.method'].browse(payment_method_id)
                                
                                # Preparar datos de tarjeta para búsqueda (misma lógica que find_applicable_promotion sin orden)
                                card_data = {
                                    'Acquirer': result.get('Acquirer', ''),
                                    'Issuer': result.get('Issuer', ''),
                                    'CardNumber': result.get('CardNumber', ''),
                                }
                                
                                provider_code = 'oca' if payment_method.use_payment_terminal == 'oca' else None
                                
                                promotion = env['payment.method.promotion'].find_applicable_promotion(
                                    card_data=card_data,
                                    provider_code=provider_code,
                                    payment_method_id=payment_method_id,
                                    order=None,
                                )

                                if promotion:
                                    _logger.info(
                                        "OCA_PROMOS_RC12: promo candidata por tarjeta | id=%s | name=%s | "
                                        "incompatible_promotion_ids=%s",
                                        promotion.id,
                                        promotion.name,
                                        promotion.incompatible_promotion_ids.ids,
                                    )
                                    applied_loyalty_ids = get_applied_loyalty_program_ids_for_oca_thread(
                                        env, pos_session_id, data
                                    )
                                    blocked, block_msg = (
                                        promotion.get_incompatibility_payment_block_for_applied_programs(
                                            applied_loyalty_ids
                                        )
                                    )
                                    _logger.info(
                                        "OCA_PROMOS_RC12: chequeo incompatibilidad | trans_id=%s | "
                                        "applied_loyalty_ids=%s | blocked=%s",
                                        transaction_id,
                                        applied_loyalty_ids,
                                        blocked,
                                    )
                                    if blocked:
                                        promotion_processed = True
                                        _logger.warning(
                                            'Pago OCA con promoción bloqueado por incompatibilidad (trans. %s): %s',
                                            transaction_id,
                                            block_msg,
                                        )
                                        reverse_result = payment_method.processFinancialReverse(
                                            query_data, base_url_endpoint
                                        )
                                        result.update({
                                            'ResponseCode': '999',
                                            'TransactionId': transaction_id,
                                            'msg': block_msg,
                                            'promotion_incompatible_cancelled': True,
                                            'reverse_after_incompatible_ok': (
                                                str(reverse_result.get('ResponseCode', '')) == '0'
                                            ),
                                            'reverse_msg': reverse_result.get('msg', ''),
                                        })
                                        _logger.info(
                                            'processFinancialReverse tras incompatibilidad promoción/lealtad: %s',
                                            pprint.pformat(reverse_result),
                                        )
                                        break

                                # Sin bloqueo por lealtad incompatible (o sin promoción por BIN)
                                promotion_processed = True
                                
                                if not promotion:
                                    _logger.info(
                                        "OCA_PROMOS_RC12: sin payment.method.promotion para esta tarjeta "
                                        "(BIN/proveedor/fechas) | trans_id=%s | CardNumber_prefix=%s",
                                        transaction_id,
                                        (str(card_data.get("CardNumber") or "")[:12]),
                                    )
                                    _logger.info('No se encontró promoción aplicable para esta transacción (BIN no coincide o no hay promociones configuradas)')
                                    _logger.info('Procesando pago normalmente sin aplicar descuento ni promoción')
                                    # Confirmar sin promoción (valores originales). Quotas = valor recibido del POS.
                                    quota_value = _get_quota_value()
                                    confirm_data = {
                                        "PosID": data['PosID'],
                                        "SystemId": data['SystemId'],
                                        "Branch": data['Branch'],
                                        "ClientAppId": data['ClientAppId'],
                                        "UserId": data['UserId'],
                                        "TransactionDateTimeyyyyMMddHHmmssSSS": payment_method.get_formatted_timestamp(),
                                        "TransactionId": str(transaction_id),  # String según documentación
                                        "Amount": data.get('Amount', '0'),
                                        "Quotas": quota_value,  # Valor recibido del POS (result) o request (data)
                                        "Plan": 0,  # Número según documentación
                                        "Currency": data.get('Currency', '858'),
                                        "TaxRefund": int(data.get('TaxRefund', 1)),  # Número según documentación
                                        "TaxableAmount": data.get('TaxableAmount', '0'),
                                        "InvoiceAmount": data.get('InvoiceAmount', '0'),
                                        "InvoiceNumber": data.get('InvoiceNumber', '1'),
                                        "TaxAmount": "0",  # Monto de impuestos (string)
                                        "TipAmount": "0",  # Monto de propina (string)
                                        "CardAccountType": "0",  # Tipo de cuenta de tarjeta (string)
                                        # Datos de la tarjeta que ya fueron leídos (requeridos por POSLink)
                                        "Acquirer": result.get('Acquirer', ''),
                                        "Issuer": result.get('Issuer', ''),
                                        "CardNumber": result.get('CardNumber', ''),
                                    }
                                    confirm_response = payment_method.processConfirmFinancialPurchase(confirm_data, pos_session_id)
                                    _logger.info('Confirmación sin promoción enviada: ResponseCode=%s', confirm_response.get('ResponseCode'))
                                    # NO hacer continue aquí - continuar con el flujo normal esperando a que la transacción se complete
                                    # El bucle seguirá consultando hasta que ResponseCode = '0' (transacción completada)
                                else:
                                    # Promoción encontrada: calcular descuento (solo si promotion es válido)
                                    original_amount = float(data.get('Amount', 0)) / 100.0  # Convertir de centavos a pesos
                                    discount_percent = promotion.discount_percent
                                    # Calcular base del descuento según tipo
                                    if promotion.discount_type == 'percentage_untaxed':
                                        # Descuento sobre subtotal sin impuestos
                                        base_amount = float(data.get('TaxableAmount', 0)) / 100.0
                                    else:
                                        # Descuento sobre total (por defecto)
                                        base_amount = original_amount
                                    discount_amount = base_amount * (discount_percent / 100.0)
                                    new_amount = original_amount - discount_amount
                                    _logger.info(
                                        "OCA_PROMOS_RC12: aplicando descuento OCA (compatible con lealtad del carrito) | "
                                        "trans_id=%s | promo_id=%s",
                                        transaction_id,
                                        promotion.id,
                                    )
                                    _logger.info('Promoción aplicable encontrada: %s (ID: %s) - %s%% de descuento - Monto original: %s, Descuento: %s, Nuevo monto: %s', 
                                               promotion.name, promotion.id, discount_percent, original_amount, discount_amount, new_amount)
                                    # Obtener producto de descuento de la promoción
                                    discount_product = promotion.discount_product_id
                                    if discount_product:
                                        # Calcular nuevos montos en centavos
                                        new_amount_cents = int(new_amount * 100)
                                        # Aproximar el taxable amount proporcionalmente
                                        original_taxable = float(data.get('TaxableAmount', 0)) / 100.0
                                        new_taxable_amount = original_taxable * (new_amount / original_amount) if original_amount > 0 else 0
                                        new_taxable_cents = int(new_taxable_amount * 100)
                                        # Preparar datos para processConfirmFinancialPurchase
                                        # Quotas = valor recibido del POS (result) o request (data)
                                        quota_value = _get_quota_value()
                                        confirm_data = {
                                            "PosID": data['PosID'],
                                            "SystemId": data['SystemId'],
                                            "Branch": data['Branch'],
                                            "ClientAppId": data['ClientAppId'],
                                            "UserId": data['UserId'],
                                            "TransactionDateTimeyyyyMMddHHmmssSSS": payment_method.get_formatted_timestamp(),
                                            "TransactionId": str(transaction_id),  # MISMO TransactionId de la transacción original (como string según documentación)
                                            "Amount": str(new_amount_cents),  # Monto con descuento aplicado (string)
                                            "Quotas": quota_value,  # Valor recibido del POS
                                            "Plan": 0,  # Número según documentación
                                            "Currency": data.get('Currency', '858'),
                                            "TaxRefund": int(data.get('TaxRefund', 1)),  # Número según documentación (1 = con IVA, 99 = sin IVA)
                                            "TaxableAmount": str(new_taxable_cents),  # String según documentación
                                            "InvoiceAmount": str(new_amount_cents),  # String según documentación
                                            "InvoiceNumber": data.get('InvoiceNumber', '1'),
                                            "TaxAmount": "0",  # Monto de impuestos (string, puede ser 0)
                                            "TipAmount": "0",  # Monto de propina (string, puede ser 0)
                                            "CardAccountType": "0",  # Tipo de cuenta de tarjeta (string, 0 = débito, 20 = crédito)
                                        }
                                        # Llamar a processConfirmFinancialPurchase para confirmar/modificar la transacción existente
                                        _logger.info('Confirmando transacción existente con monto modificado usando processConfirmFinancialPurchase: %s (original: %s, descuento: %s)', 
                                                   new_amount, original_amount, discount_amount)
                                        _logger.info('TransactionId original que se está confirmando: %s', transaction_id)
                                        confirm_response = payment_method.processConfirmFinancialPurchase(confirm_data, pos_session_id)
                                        _logger.info('Respuesta de processConfirmFinancialPurchase: %s', pprint.pformat(confirm_response))
                                        # Almacenar información de promoción independientemente del resultado
                                        saved_promotion_info = {
                                            'promotion_id': promotion.id,
                                            'promotion_name': promotion.name,
                                            'discount_percent': discount_percent,
                                            'discount_type': promotion.discount_type,
                                            'discount_amount': discount_amount,
                                            'original_amount': original_amount,
                                            'new_amount': new_amount,
                                            'product_id': discount_product.id,
                                            'description': f'{promotion.name} - {discount_percent}%',
                                            'is_promotion': True
                                        }
                                        try:
                                            promotion.action_increment_times_applied()
                                        except Exception as counter_error:
                                            _logger.warning('Error al incrementar contador de promoción: %s', str(counter_error))
                                        result['promotion_info'] = saved_promotion_info
                                        _logger.info('Información de promoción almacenada en resultado para transacción OCA: %s', transaction_id)
                                        if confirm_response.get('ResponseCode') in ['0', '10']:
                                            _logger.info('Promoción procesada y processConfirmFinancialPurchase enviado exitosamente')
                                        else:
                                            _logger.warning('processConfirmFinancialPurchase devolvió código %s: %s. Continuando con promoción almacenada.', 
                                                          confirm_response.get('ResponseCode'), confirm_response.get('msg'))
                                    else:
                                        _logger.warning('No se encontró producto de descuento en la promoción %s, confirmando sin promoción', promotion.name)
                                        quota_value = _get_quota_value()
                                        confirm_data = {
                                            "PosID": data['PosID'],
                                            "SystemId": data['SystemId'],
                                            "Branch": data['Branch'],
                                            "ClientAppId": data['ClientAppId'],
                                            "UserId": data['UserId'],
                                            "TransactionDateTimeyyyyMMddHHmmssSSS": payment_method.get_formatted_timestamp(),
                                            "TransactionId": str(transaction_id),
                                            "Amount": data.get('Amount', '0'),
                                            "Quotas": quota_value,
                                            "Plan": 0,
                                            "Currency": data.get('Currency', '858'),
                                            "TaxRefund": int(data.get('TaxRefund', 1)),
                                            "TaxableAmount": data.get('TaxableAmount', '0'),
                                            "InvoiceAmount": data.get('InvoiceAmount', '0'),
                                            "InvoiceNumber": data.get('InvoiceNumber', '1'),
                                            "TaxAmount": "0",
                                            "TipAmount": "0",
                                            "CardAccountType": "0",
                                            "Acquirer": result.get('Acquirer', ''),
                                            "Issuer": result.get('Issuer', ''),
                                            "CardNumber": result.get('CardNumber', ''),
                                        }
                                        confirm_response = payment_method.processConfirmFinancialPurchase(confirm_data, pos_session_id)
                                        _logger.info('Confirmación sin promoción enviada: ResponseCode=%s', confirm_response.get('ResponseCode'))
                            except Exception as promo_error:
                                _logger.error('Error al procesar promoción automáticamente: %s', str(promo_error))
                                import traceback
                                _logger.error('Traceback: %s', traceback.format_exc())
                                # Continuar sin promoción - procesar pago normalmente. Quotas = valor recibido del POS.
                                try:
                                    payment_method = env['pos.payment.method'].browse(payment_method_id)
                                    quota_value = _get_quota_value()
                                    confirm_data = {
                                        "PosID": data['PosID'],
                                        "SystemId": data['SystemId'],
                                        "Branch": data['Branch'],
                                        "ClientAppId": data['ClientAppId'],
                                        "UserId": data['UserId'],
                                        "TransactionDateTimeyyyyMMddHHmmssSSS": payment_method.get_formatted_timestamp(),
                                        "TransactionId": str(transaction_id),  # String según documentación
                                        "Amount": data.get('Amount', '0'),
                                        "Quotas": quota_value,  # Valor recibido del POS
                                        "Plan": 0,  # Número según documentación
                                        "Currency": data.get('Currency', '858'),
                                        "TaxRefund": int(data.get('TaxRefund', 1)),  # Número según documentación
                                        "TaxableAmount": data.get('TaxableAmount', '0'),
                                        "InvoiceAmount": data.get('InvoiceAmount', '0'),
                                        "InvoiceNumber": data.get('InvoiceNumber', '1'),
                                        "TaxAmount": "0",  # Monto de impuestos (string)
                                        "TipAmount": "0",  # Monto de propina (string)
                                        "CardAccountType": "0",  # Tipo de cuenta de tarjeta (string)
                                        # Datos de la tarjeta que ya fueron leídos (requeridos por POSLink)
                                        "Acquirer": result.get('Acquirer', ''),
                                        "Issuer": result.get('Issuer', ''),
                                        "CardNumber": result.get('CardNumber', ''),
                                    }
                                    confirm_response = payment_method.processConfirmFinancialPurchase(confirm_data, pos_session_id)
                                    _logger.info('Confirmación sin promoción (por error) enviada: ResponseCode=%s', confirm_response.get('ResponseCode'))
                                    # NO hacer continue aquí - continuar con el flujo normal esperando a que la transacción se complete
                                except Exception as confirm_error:
                                    _logger.error('Error al confirmar sin promoción: %s', str(confirm_error))
                                    import traceback
                                    _logger.error('Traceback: %s', traceback.format_exc())
                                    # Aunque haya error, continuar con el flujo normal para no quedar trabado
                    
                    # Si el código de respuesta no es de espera, salir del loop
                    # IMPORTANTE: Preservar promotion_info si existe antes de salir
                    if response_code not in ['10', '12']:
                        # Si hay información de promoción guardada, asegurarse de que esté en el result final
                        if saved_promotion_info:
                            result['promotion_info'] = saved_promotion_info
                            _logger.info('Preservando promotion_info en resultado final (ResponseCode: %s)', response_code)
                        break

                    # Si el tiempo de espera expiró (RemainingExpirationTime == 0.0)
                    if response_code in ['10', '12'] and rt == 0.0:
                        _logger.warning('Tiempo de espera expirado para transacción %s. Procesando reversión...', transaction_id)
                        reverse_result = env['pos.payment.method'].browse(payment_method_id).processFinancialReverse(query_data, base_url_endpoint)
                        _logger.info('Resultado de reversión: %s', pprint.pformat(reverse_result))
                        
                        result = {
                            'ResponseCode': '11',
                            'msg': 'Tiempo de transacción excedido, envíe datos nuevamente.',
                            'TransactionId': transaction_id,
                            'RemainingExpirationTime': 0.0,
                            'timeout_error': True,
                            'reverse_processed': True,
                        }
                        
                        if reverse_result.get('ResponseCode') == '0':
                            result['reverse_success'] = True
                            result['reverse_msg'] = 'Reversión procesada exitosamente'
                        else:
                            result['reverse_success'] = False
                            result['reverse_msg'] = reverse_result.get('msg', 'Error en reversión')
                        
                        break

                except Exception as e:
                    _logger.error('Error en procesamiento en segundo plano: %s', str(e))
                    result = {
                        'ResponseCode': '999',
                        'msg': 'Error no determinado.',
                        'TransactionId': transaction_id,
                        'error': str(e),
                    }
                    break
                _logger.info('>>>FIN Intento Promociones>>>')

            # Actualizar la transacción almacenada con la información final
            # Asegurarse de que promotion_info esté presente si se procesó una promoción
            if saved_promotion_info and 'promotion_info' not in result:
                result['promotion_info'] = saved_promotion_info
                _logger.info('Restaurando promotion_info en resultado final antes de actualizar transacción')
            
            # Mensaje legible según códigos POSLink v135 (Anexos 1 y 2) para usuario y transacción
            result['msg'] = env['payment.transaction'].get_oca_display_message(result)
            
            try:
                env['pos.payment.method']._update_stored_transaction_with_session(transaction_id, result, pos_session_id)
            except Exception as e:
                _logger.error('Error al actualizar transacción en segundo plano: %s', str(e))

            # Enviar mensaje final al bus
            result.update({
                'id_config': id_config,
                'origin_transaction_id': transaction_id,
            })
            try:
                env['bus.bus'].sudo()._sendone(bus_channel_name, 'OCA_LATEST_RESPONSE', result)
            except Exception as e:
                _logger.error('Error al enviar mensaje bus final: %s', str(e))

    @api.model
    def get_promotion_info(
        self, card_data, pos_session_id, pos_order_id=False, applied_loyalty_program_ids=None
    ):
        """
        Obtiene información de promoción basada en datos de la tarjeta
        
        Busca promociones configuradas en payment.method.promotion que coincidan
        con los criterios de la tarjeta (proveedor, BIN, etc.)
        
        Args:
            card_data (dict): Datos de la tarjeta con keys:
                - Acquirer: Adquirente (ej: "VISA", "MASTERCARD")
                - Issuer: Emisor (código o dict con code/name)
                - CardNumber: Número de tarjeta o BIN
            pos_session_id (int): ID de la sesión POS
            pos_order_id (int|False): pos.order opcional para calcular montos de descuento.
            applied_loyalty_program_ids (list|None): IDs de lealtad del carrito (POS); si es None se usan sesión + borrador.
        
        Returns:
            dict: Información de promoción con keys:
                - hasPromotion: bool - Si hay promoción aplicable
                - discountAmount: float - Monto del descuento
                - productId: int - ID del producto de descuento
                - description: str - Descripción del descuento
                - blockedByIncompatibility: bool - Si hay promo por tarjeta pero lealtad aplicada incompatible
                - userMessage: str - Mensaje para mostrar en el POS si está bloqueado
        """
        self.ensure_one()
        
        try:
            # Buscar promoción aplicable según configuración
            provider_code = 'oca' if self.use_payment_terminal == 'oca' else None
            
            promotion = self.env['payment.method.promotion'].find_applicable_promotion(
                card_data=card_data,
                provider_code=provider_code,
                payment_method_id=self.id,
                order=None,
            )
            
            if not promotion:
                _logger.info(
                    "OCA_PROMOS get_promotion_info: sin promo por tarjeta | payment_method_id=%s | "
                    "pos_session_id=%s | CardNumber_prefix=%s",
                    self.id,
                    pos_session_id,
                    (str((card_data or {}).get("CardNumber") or ""))[:12],
                )
                return {
                    'hasPromotion': False,
                    'discountAmount': 0.0,
                    'productId': False,
                    'description': '',
                    'blockedByIncompatibility': False,
                    'userMessage': '',
                    'promotionId': False,
                }

            resolved_loyalty_ids = []
            if applied_loyalty_program_ids not in (None, False):
                try:
                    resolved_loyalty_ids = [
                        int(x)
                        for x in applied_loyalty_program_ids
                        if x is not None and str(x).strip() != ""
                    ]
                except (TypeError, ValueError):
                    resolved_loyalty_ids = []
                _logger.info(
                    "OCA_PROMOS get_promotion_info: lealtad desde RPC (POS) | ids=%s | "
                    "promo_id=%s | incompatible_config_ids=%s",
                    resolved_loyalty_ids,
                    promotion.id,
                    promotion.incompatible_promotion_ids.ids,
                )
            else:
                resolved_loyalty_ids = get_applied_loyalty_program_ids_for_oca_thread(
                    self.env, pos_session_id, {}
                )
                _logger.info(
                    "OCA_PROMOS get_promotion_info: lealtad resuelta en servidor (sesión+borrador) | "
                    "ids=%s | promo_id=%s",
                    resolved_loyalty_ids,
                    promotion.id,
                )

            blocked, block_msg = (
                promotion.get_incompatibility_payment_block_for_applied_programs(
                    resolved_loyalty_ids
                )
            )
            if blocked:
                _logger.warning(
                    "OCA_PROMOS get_promotion_info: BLOQUEADO | promo_id=%s | applied_loyalty=%s | msg=%s",
                    promotion.id,
                    resolved_loyalty_ids,
                    block_msg,
                )
                return {
                    'hasPromotion': False,
                    'discountAmount': 0.0,
                    'productId': promotion.discount_product_id.id,
                    'description': promotion.name,
                    'blockedByIncompatibility': True,
                    'userMessage': block_msg,
                    'promotionId': promotion.id,
                }

            _logger.info(
                "OCA_PROMOS get_promotion_info: OK compatibilidad lealtad | promo_id=%s | "
                "applied_loyalty_ids=%s → se calcula descuento",
                promotion.id,
                resolved_loyalty_ids,
            )

            pos_order = self.env['pos.order']
            if pos_order_id:
                pos_order = pos_order.browse(int(pos_order_id)).exists()
            if not pos_order:
                pos_order = self.env['pos.order'].search([
                    ('session_id', '=', pos_session_id),
                    ('state', '=', 'draft'),
                ], order='id desc', limit=1)
            if not pos_order:
                pos_order = self.env['pos.order'].search([
                    ('session_id', '=', pos_session_id)
                ], order='id desc', limit=1)
            
            if not pos_order:
                _logger.warning('No se encontró orden POS para calcular descuento')
                return {
                    'hasPromotion': False,
                    'discountAmount': 0.0,
                    'productId': promotion.discount_product_id.id,
                    'description': promotion.name,
                    'blockedByIncompatibility': False,
                    'userMessage': '',
                    'promotionId': promotion.id,
                }
            
            # Calcular descuento según tipo de promoción
            if promotion.discount_type == 'percentage_untaxed':
                base_amount = pos_order.amount_untaxed
            else:
                base_amount = pos_order.amount_total
            
            discount_amount = base_amount * (promotion.discount_percent / 100.0)
            
            _logger.info('Promoción aplicable encontrada: %s (ID: %s) - %s%% de descuento sobre %s = %s', 
                       promotion.name, promotion.id, promotion.discount_percent, 
                       'subtotal' if promotion.discount_type == 'percentage_untaxed' else 'total',
                       discount_amount)
            
            return {
                'hasPromotion': True,
                'discountAmount': discount_amount,
                'productId': promotion.discount_product_id.id,
                'description': f'{promotion.name} - {promotion.discount_percent}%',
                'blockedByIncompatibility': False,
                'userMessage': '',
                'promotionId': promotion.id,
            }
            
        except Exception as e:
            _logger.error('Error al obtener información de promoción: %s', str(e))
            import traceback
            _logger.error('Traceback: %s', traceback.format_exc())
            return {
                'hasPromotion': False,
                'discountAmount': 0.0,
                'productId': False,
                'description': '',
                'blockedByIncompatibility': False,
                'userMessage': '',
                'promotionId': False,
            }

