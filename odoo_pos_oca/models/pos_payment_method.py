import threading
import pprint
import logging
import requests

from time import sleep
from odoo import fields, models, api, SUPERUSER_ID
from datetime import datetime

from odoo.addons.l10n_be_coda.models.account_journal import transaction_code

_logger = logging.getLogger("POS PAYMENT METHOD")


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super(PosPaymentMethod, self)._get_payment_terminal_selection() + [('oca', 'OCA')]

    def get_formatted_timestamp(self):
        now = datetime.now()
        return now.strftime('%Y%m%d%H%M%S') + f'{int(now.microsecond / 1000):03d}'

    url_webservice = fields.Char('URL servicio web')
    codigo_sistema = fields.Char('Código Sistema (SystemId)')
    codigo_terminal = fields.Char('Código Terminal (PosID)')
    client_app_id = fields.Char('Client APP ID', default='1')
    codigo_sucursal = fields.Integer('Código Sucursal')

    # Multi-POS (antes en odoo_pos_oca_multiple). El modelo y los campos del
    # provider viven en odoo_pos_oca_multiple; aquí solo las referencias para
    # que el TPV pueda elegir qué PosID usar cuando el proveedor es multi.
    is_multiple = fields.Boolean('Tiene multiples POS')
    payment_provider = fields.Many2one(
        comodel_name='payment.provider',
        string='Proveedor de Pago Asociado',
    )
    pos_id = fields.Many2one(
        'multiple.pos.config',
        string='POS Asociado',
    )

    @api.onchange('payment_provider', 'payment_provider.is_multiple')
    def _onchange_payment_provider(self):
        for rec in self:
            if rec.payment_provider:
                rec.url_webservice = rec.payment_provider.url_webservice
                rec.codigo_sistema = rec.payment_provider.codigo_sistema
                rec.client_app_id = rec.payment_provider.client_app_id
                rec.codigo_sucursal = rec.payment_provider.codigo_sucursal
                rec.is_multiple = rec.payment_provider.is_multiple

    @api.onchange('pos_id')
    def _onchange_pos_id(self):
        for rec in self:
            if rec.pos_id:
                rec.codigo_terminal = rec.pos_id.codigo_terminal

    def enviar_pago(self, data, pos_session_id, has_refunded_line):
        self.ensure_one()
        if not has_refunded_line:
            return self.processFinancialPurchase(data, pos_session_id)

        return self.processFinancialPurchaseVoidByTicket(data, pos_session_id)

    def processFinancialPurchase(self, data, pos_session_id, account_payment_id=None):
        """
        Procesa una compra financiera enviando datos al POS y almacenando la transacción.

        Args:
            data (dict): Datos de la transacción a enviar al POS
            pos_session_id (int): ID de la sesión POS
            account_payment_id (int|None): Compatibilidad con odoo_pos_fiserv (pago contable + terminal);
                en flujo OCA puro no se usa; si hay super() en la cadena, debe propagarse.

        Returns:
            dict: Respuesta del POS
        """
        self.ensure_one()
        # Terminal Fiserv: la implementación vive en odoo_pos_fiserv (incl. account_payment_id).
        if self.use_payment_terminal == 'fiserv':
            return super(PosPaymentMethod, self).processFinancialPurchase(
                data, pos_session_id, account_payment_id=account_payment_id
            )
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]

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

        if response_json['ResponseCode'] == '0':
            # Iniciar hilo para procesamiento en segundo plano
            transaction_id = response_json['TransactionId']
            # Pasar también la información de la sesión para evitar problemas de búsqueda
            threading.Thread(target=self._procesar_en_segundo_plano, 
                           args=(data, bus_channel_name, id_config, transaction_id, base_url_endpoint, pos_session_id)).start()

        return response_json

    def _store_oca_transaction(self, pos_data, oca_response, pos_session_id):
        """
        Almacena la información de la transacción OCA en payment.transaction
        SOLO cuando recibimos respuesta del POS
        
        Args:
            pos_data (dict): Datos enviados al POS
            oca_response (dict): Respuesta recibida del POS
            pos_session_id (int): ID de la sesión POS
        """
        try:
            # Buscar el pedido POS relacionado
            pos_order = self._find_related_pos_order_by_transaction_with_data(oca_response.get('TransactionId', ''), pos_session_id, pos_data)
            pos_payment = self._find_related_pos_payment(pos_data, pos_session_id)
            
            # Crear la transacción en payment.transaction
            self.env['payment.transaction'].sudo().create_oca_transaction(
                pos_data=pos_data,
                oca_response=oca_response,
                pos_order=pos_order,
                pos_payment=pos_payment
            )
            
            _logger.info('Transacción OCA almacenada exitosamente después de recibir respuesta del POS')
            
        except Exception as e:
            _logger.error('Error al almacenar transacción OCA: %s', str(e))

    def _find_related_pos_order_by_transaction_with_data(self, transaction_id, pos_session_id, pos_data):
        """
        Busca el pedido POS relacionado con una transacción usando los datos del POS
        
        Args:
            transaction_id (str): ID de la transacción OCA
            pos_session_id (int): ID de la sesión POS
            pos_data (dict): Datos enviados al POS
            
        Returns:
            pos.order: Pedido POS encontrado o None
        """
        try:
            # Intentar encontrar el pedido por el número de factura que viene en los datos del POS
            invoice_number = pos_data.get('InvoiceNumber')
            if invoice_number:
                _logger.info('Buscando pedido POS por InvoiceNumber: %s en sesión: %s', invoice_number, pos_session_id)
                
                # Buscar por tracking_number del pedido
                pos_orders = self.env['pos.order'].search([
                    ('session_id', '=', pos_session_id)
                ])
                
                for order in pos_orders:
                    if order.tracking_number:
                        # Formatear el tracking_number para comparar (máximo 7 caracteres)
                        order_tracking = str(order.tracking_number)
                        if len(order_tracking) > 7:
                            order_tracking = order_tracking[-7:]
                        else:
                            order_tracking = order_tracking.zfill(7)
                        
                        if order_tracking == invoice_number:
                            _logger.info('Pedido POS encontrado por tracking_number: %s (InvoiceNumber: %s)', order.name, invoice_number)
                            return order

                # Coincidir con el formato del POS: últimos 7 dígitos del id de pos.order rellenados a 7
                # (evita depender solo de tracking_number, a menudo vacío en borradores).
                inv_norm = str(invoice_number).strip()
                for order in pos_orders:
                    oid_suffix = str(order.id)[-7:].zfill(7)
                    if oid_suffix == inv_norm:
                        _logger.info(
                            'Pedido POS encontrado por id (sufijo 7 dígitos): %s (InvoiceNumber: %s)',
                            order.name,
                            invoice_number,
                        )
                        return order

                # Solo tratar como id numérico de BD si la cadena es canónica (sin ceros a la izquierda
                # artificiales): int('0000201') == 201 sería un falso positivo frente al formato ITD de 7 dígitos.
                try:
                    if inv_norm.isdigit() and str(int(inv_norm)) == inv_norm:
                        order_id = int(inv_norm)
                        _logger.info('Intentando buscar por ID del pedido: %s', order_id)
                        pos_order = self.env['pos.order'].search(
                            [
                                ('id', '=', order_id),
                                ('session_id', '=', pos_session_id),
                            ],
                            limit=1,
                        )
                        if pos_order:
                            _logger.info(
                                'Pedido POS encontrado por ID: %s (InvoiceNumber: %s)',
                                pos_order.name,
                                invoice_number,
                            )
                            return pos_order
                        _logger.warning(
                            'No se encontró pedido con ID %s en sesión %s',
                            order_id,
                            pos_session_id,
                        )
                except (ValueError, TypeError) as e:
                    _logger.warning('Error al convertir InvoiceNumber a ID: %s', str(e))
            
            # Si no se encuentra por InvoiceNumber, NO usar más el fallback de
            # \"último pedido de la sesión\" porque puede asociar la transacción
            # a la orden anterior en lugar de la orden actual.
            #
            # En su lugar, dejamos la transacción sin pos_order_id y delegamos
            # la asociación final a pos.order._associate_oca_transactions()
            # cuando se cree y registre efectivamente la orden.
            _logger.info(
                'No se encontró pedido POS por InvoiceNumber para transacción %s en sesión %s. '
                'Se deja sin pedido asociado y se delega asociación a pos.order._associate_oca_transactions.',
                transaction_id,
                pos_session_id,
            )
            return self.env['pos.order']
            
        except Exception as e:
            _logger.error('Error al buscar pedido POS relacionado: %s', str(e))
            return None

    def _find_related_pos_payment(self, pos_data, pos_session_id):
        """
        Busca el pago POS relacionado con la transacción
        
        Args:
            pos_data (dict): Datos de la transacción
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.payment: Pago POS encontrado o None
        """
        try:
            # Obtener el monto del POS (está en centavos)
            pos_amount = pos_data.get('Amount', 0.0)
            if isinstance(pos_amount, str):
                try:
                    pos_amount = float(pos_amount)
                except (ValueError, TypeError):
                    pos_amount = 0.0
            
            # Convertir el monto del POS desde centavos a la unidad correcta
            pos_amount_corrected = pos_amount / 100.0 if pos_amount > 0 else 0.0
            
            # Log para debuggear la búsqueda del pago POS
            _logger.info('OCA Payment Search Debug - POS Amount: %s, Corrected: %s, Session: %s', 
                        pos_amount, pos_amount_corrected, pos_session_id)
            
            if pos_amount_corrected > 0:
                # Buscar pagos recientes en la sesión que coincidan con el monto corregido
                pos_payment = self.env['pos.payment'].search([
                    ('session_id', '=', pos_session_id),
                    ('amount', '=', pos_amount_corrected),
                    ('payment_method_id', '=', self.id)
                ], order='id desc', limit=1)
                
                if not pos_payment:
                    # Si no se encuentra con el monto exacto, buscar con una tolerancia
                    # para manejar diferencias de redondeo
                    tolerance = 0.01  # 1 centavo de tolerancia
                    pos_payment = self.env['pos.payment'].search([
                        ('session_id', '=', pos_session_id),
                        ('amount', '>=', pos_amount_corrected - tolerance),
                        ('amount', '<=', pos_amount_corrected + tolerance),
                        ('payment_method_id', '=', self.id)
                    ], order='id desc', limit=1)
                
                return pos_payment
        except Exception as e:
            _logger.error('Error al buscar pago POS relacionado: %s', str(e))
        
        return None

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
        Procesa la transacción en segundo plano y actualiza la información almacenada.

        Args:
            data (dict): Datos originales de la transacción
            bus_channel_name (str): Nombre del canal de bus
            id_config (int): ID de la configuración
            transaction_id (str): ID de la transacción
            base_url_endpoint (str): URL base del endpoint
            pos_session_id (int): ID de la sesión POS
            account_payment_id (int|None): odoo_pos_fiserv (pago contable + ITD)
            user_id (int|None): Usuario del cursor en el hilo Fiserv
        """
        # Terminal Fiserv: el bucle ITD y el post de account.payment están en odoo_pos_fiserv
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
        # para usarlo dentro del nuevo entorno
        payment_method_id = self.id
        
        # Nuevo cursor y entorno para evitar problemas de ORM compartido
        with self.pool.cursor() as new_cr:
            env = api.Environment(new_cr, SUPERUSER_ID, {})
            result = {}

            data = {
                "PosID": data['PosID'],
                "SystemId": data['SystemId'],
                "Branch": data['Branch'],
                "ClientAppId": data['ClientAppId'],
                "UserId": data['UserId'],
                "TransactionDateTimeyyyyMMddHHmmssSSS": env['pos.payment.method'].get_formatted_timestamp(),
                "TransactionId": transaction_id,
            }

            # POSLink/OCA no garantiza que TODOS los datos importantes (Quota,
            # Ticket, Batch, AuthorizationCode, CardNumber, etc.) lleguen en la
            # MISMA respuesta. A veces ``Quota`` aparece en una iteración con
            # RC=12 y luego desaparece del payload final con RC=0. Si solo
            # persistimos el último ``result``, la cuota queda en 1.
            #
            # Acumulamos los valores no-vacíos de cada iteración y al final los
            # mergeamos sobre la respuesta final: campos como ``Quota`` o
            # ``Ticket`` se rellenan desde el accumulator si la última respuesta
            # no los trae, sin pisar valores válidos.
            accumulated = {}
            mergeable_keys = (
                'Quota', 'Quotas', 'Installments', 'installments',
                'Ticket', 'Batch', 'AuthorizationCode', 'Merchant',
                'CardNumber', 'Issuer', 'Acquirer', 'PosID',
                'EmvApplicationName', 'TransactionDate', 'TransactionHour',
            )

            while True:
                sleep(4)
                _logger.info('>>>Intento>>>')
                try:
                    result = env['pos.payment.method'].processFinancialPurchaseQuery(data, base_url_endpoint)
                    _logger.info('Result: %s', pprint.pformat(result))

                    response_code = result['ResponseCode']
                    rt = result['RemainingExpirationTime'] if 'RemainingExpirationTime' in result else False

                    # Acumular valores útiles antes de evaluar exit del loop:
                    # cubre el caso en que la última iteración los pierda.
                    for key in mergeable_keys:
                        val = result.get(key)
                        if val in (None, '', False):
                            continue
                        # Excluir ceros que el pinpad usa como "aún no elegido".
                        if isinstance(val, (int, float)) and val == 0:
                            continue
                        if isinstance(val, str) and val.strip() in ('', '0'):
                            continue
                        accumulated[key] = val

                    # Si el código de respuesta no es de espera, salir del loop
                    if response_code not in ['10', '12']:
                        break

                    # Si el tiempo de espera expiró (RemainingExpirationTime == 0.0)
                    # se debe procesar la reversión y notificar al POS para liberarlo
                    if response_code in ['10', '12'] and rt == 0.0:
                        _logger.warning('Tiempo de espera expirado para transacción %s. Procesando reversión...', transaction_id)
                        
                        # Procesar la reversión para devolver el dinero
                        # Usar env en lugar de self para evitar problemas de cursor
                        reverse_result = env['pos.payment.method'].browse(payment_method_id).processFinancialReverse(data, base_url_endpoint)
                        _logger.info('Resultado de reversión: %s', pprint.pformat(reverse_result))
                        
                        # Construir una respuesta de error para notificar al POS
                        # Usar código '11' que indica "Tiempo de transacción excedido"
                        result = {
                            'ResponseCode': '11',
                            'msg': 'Tiempo de transacción excedido, envíe datos nuevamente.',
                            'TransactionId': transaction_id,
                            'RemainingExpirationTime': 0.0,
                            'timeout_error': True,  # Flag adicional para identificar timeout
                            'reverse_processed': True,  # Indica que se procesó la reversión
                        }
                        
                        # Si la reversión fue exitosa, agregar información adicional
                        if reverse_result.get('ResponseCode') == '0':
                            result['reverse_success'] = True
                            result['reverse_msg'] = 'Reversión procesada exitosamente'
                        else:
                            result['reverse_success'] = False
                            result['reverse_msg'] = reverse_result.get('msg', 'Error en reversión')
                        
                        _logger.warning('Timeout detectado. Notificando al POS para liberar la transacción.')
                        # Salir del loop inmediatamente después de procesar la reversión
                        break

                except Exception as e:
                    _logger.error('Error en procesamiento en segundo plano: %s', str(e))
                    # En caso de error, construir una respuesta de error para el POS
                    result = {
                        'ResponseCode': '999',
                        'msg': 'Error no determinado.',
                        'TransactionId': transaction_id,
                        'error': str(e),
                    }
                    break
                _logger.info('>>>FIN Intento>>>')

            # Mergear el accumulator sobre el result final: solo campos que
            # falten o vengan vacíos en la última respuesta. Garantiza que
            # ``Quota`` y otros datos capturados en iteraciones intermedias
            # lleguen al persist (causa raíz del bug "cuota queda en 1").
            for key, val in accumulated.items():
                current = result.get(key)
                is_empty = (
                    current in (None, '', False)
                    or (isinstance(current, (int, float)) and current == 0)
                    or (isinstance(current, str) and current.strip() in ('', '0'))
                )
                if is_empty:
                    result[key] = val
            _logger.info(
                'OCA Query loop final result tras merge (tx=%s):\n%s',
                transaction_id, pprint.pformat(result),
            )

            # Actualizar la transacción almacenada con la información final
            # Usar el nuevo cursor para evitar problemas
            try:
                env['pos.payment.method']._update_stored_transaction_with_session(transaction_id, result, pos_session_id)
            except Exception as e:
                _logger.error('Error al actualizar transacción en segundo plano: %s', str(e))

            # Luego puedes enviar un mensaje al POS usando el bus
            result.update({
                'id_config': id_config,
                'origin_transaction_id': transaction_id,
            })
            try:
                env['bus.bus'].sudo()._sendone(bus_channel_name, 'OCA_LATEST_RESPONSE', result)
            except Exception as e:
                _logger.error('Error al enviar mensaje bus: %s', str(e))

    def _update_stored_transaction(self, transaction_id, final_result):
        """
        Actualiza la transacción almacenada con la información final del procesamiento
        O crea la transacción si no existe (cuando tenemos información completa)
        
        Args:
            transaction_id (str): ID de la transacción OCA
            final_result (dict): Resultado final del procesamiento
        """
        try:
            # Buscar la transacción por el ID de OCA
            transaction = self.env['payment.transaction'].sudo().search([
                ('oca_transaction_id', '=', transaction_id)
            ], limit=1)
            
            if transaction:
                # Si la transacción ya existe, actualizarla
                transaction.update_oca_transaction(final_result)
                _logger.info('Transacción OCA actualizada exitosamente con información final')
            else:
                # Si la transacción no existe, crearla con la información completa
                # Esto sucede cuando la respuesta inicial fue exitosa y ahora tenemos todos los datos
                self._create_oca_transaction_with_complete_data(transaction_id, final_result)
                _logger.info('Transacción OCA creada exitosamente con información completa')
                
        except Exception as e:
            _logger.error('Error al actualizar/crear transacción OCA: %s', str(e))

    def _try_delegate_fiserv_itd_create(self, transaction_id, final_result, pos_session_id):
        """
        Si la sesión tiene un método POS Fiserv con el mismo PosID que la respuesta ITD,
        crea payment.transaction vía flujo Fiserv y devuelve True.

        Args:
            transaction_id (str): ID ITD normalizado.
            final_result (dict): Payload pinpad.
            pos_session_id (int|None): Sesión POS.

        Returns:
            bool: True si ya se creó la transacción Fiserv.
        """
        if not pos_session_id:
            return False
        pm = self._resolve_itd_pos_payment_method_for_session(
            pos_session_id, final_result.get('PosID')
        )
        if (
            not pm
            or pm.use_payment_terminal != 'fiserv'
            or not hasattr(self.env['payment.transaction'], 'create_fiserv_transaction_with_complete_data')
        ):
            return False
        _logger.info(
            'Delegando creación ITD a Fiserv (id=%s, sesión=%s, método=%s)',
            transaction_id,
            pos_session_id,
            pm.display_name,
        )
        pm._create_fiserv_transaction_with_complete_data(
            transaction_id, final_result, pos_session_id
        )
        return True

    def _create_oca_transaction_with_complete_data(self, transaction_id, final_result, pos_session_id=None):
        """
        Crea un payment.transaction con la respuesta completa del pinpad ITD.

        Si el método de pago del TPV que coincide con PosID es Fiserv y está instalado
        odoo_pos_fiserv, delega en _create_fiserv_transaction_with_complete_data para
        que provider, método de pago y fiserv_transaction_id sean correctos.

        Args:
            transaction_id (str): ID de la transacción ITD
            final_result (dict): Resultado final con información completa
            pos_session_id (int): ID de la sesión POS (opcional)
        """
        try:
            tid = str(transaction_id).strip()
            # --- Primera oportunidad: sesión ya conocida (p. ej. hilo promociones) ---
            if self._try_delegate_fiserv_itd_create(tid, final_result, pos_session_id):
                return

            _logger.info('Creando transacción OCA con información completa para ID: %s', tid)
            
            pos_session = None
            pos_order = None
            pos_payment = None
            
            if pos_session_id:
                # Usar directamente el ID de la sesión si está disponible
                pos_session = self.env['pos.session'].browse(pos_session_id)
                if pos_session.exists():
                    _logger.info('Usando sesión POS proporcionada: %s', pos_session_id)
                    pos_order = self._find_related_pos_order_by_transaction(tid, pos_session_id)
                    pos_payment = self._find_related_pos_payment_by_transaction(tid, pos_session_id)
                else:
                    _logger.warning('Sesión POS %s no existe, buscando alternativas', pos_session_id)
                    pos_session = None
            
            if not pos_session:
                # Buscar el pedido POS relacionado usando el transaction_id
                pos_session = self._find_session_by_transaction_id(tid)
                
                if not pos_session:
                    _logger.warning('No se encontró sesión POS para la transacción: %s. Creando transacción sin relaciones.', tid)
                    # Crear la transacción sin relaciones específicas
                    self.env['payment.transaction'].sudo().create_oca_transaction_with_complete_data(
                        oca_response=final_result,
                        pos_order=None,
                        pos_payment=None,
                        transaction_id=tid
                    )
                    return
                
                # Buscar el pedido POS relacionado
                pos_order = self._find_related_pos_order_by_transaction(tid, pos_session.id)
                pos_payment = self._find_related_pos_payment_by_transaction(tid, pos_session.id)
            
            # --- Segunda oportunidad: sesión hallada por id ITD cuando no vino pos_session_id ---
            if pos_session and self._try_delegate_fiserv_itd_create(tid, final_result, pos_session.id):
                return

            _logger.info('Relaciones encontradas - Sesión: %s, Pedido: %s, Pago: %s', 
                        pos_session.id, pos_order.id if pos_order else 'None', pos_payment.id if pos_payment else 'None')
            
            # Crear la transacción con información completa
            transaction = self.env['payment.transaction'].sudo().create_oca_transaction_with_complete_data(
                oca_response=final_result,
                pos_order=pos_order,
                pos_payment=pos_payment,
                transaction_id=tid
            )
            
            _logger.info('Transacción OCA creada exitosamente con ID: %s', transaction.id)
            
        except Exception as e:
            _logger.error('Error al crear transacción OCA con información completa: %s', str(e))
            # Intentar crear la transacción sin relaciones como último recurso
            try:
                self.env['payment.transaction'].sudo().create_oca_transaction_with_complete_data(
                    oca_response=final_result,
                    pos_order=None,
                    pos_payment=None,
                    transaction_id=tid
                )
                _logger.info('Transacción OCA creada sin relaciones como fallback')
            except Exception as fallback_error:
                _logger.error('Error al crear transacción OCA como fallback: %s', str(fallback_error))

    def _find_session_by_transaction_id(self, transaction_id):
        """
        Busca la sesión POS relacionada con una transacción
        
        Args:
            transaction_id (str): ID de la transacción OCA
            
        Returns:
            pos.session: Sesión POS encontrada o None
        """
        _logger.info('Buscando sesión POS para transacción: %s', transaction_id)
        
        # Primero, intentar buscar en las transacciones existentes
        existing_transaction = self.env['payment.transaction'].sudo().search([
            ('oca_transaction_id', '=', transaction_id)
        ], limit=1)
        
        if existing_transaction:
            _logger.info('Transacción ya existe, usando sesión existente')
            if existing_transaction.pos_order_id and existing_transaction.pos_order_id.session_id:
                return existing_transaction.pos_order_id.session_id
            elif existing_transaction.pos_payment_id and existing_transaction.pos_payment_id.session_id:
                return existing_transaction.pos_payment_id.session_id
        
        # Buscar en las sesiones recientes que tengan pagos OCA
        recent_sessions = self.env['pos.session'].search([
            ('state', '=', 'opened')
        ], order='id desc', limit=20)  # Aumentar el límite para buscar más sesiones
        
        _logger.info('Sesiones abiertas encontradas: %s', len(recent_sessions))
        
        for session in recent_sessions:
            _logger.info('Verificando sesión: %s', session.id)
            
            # Buscar pagos OCA en esta sesión
            oca_payments = self.env['pos.payment'].search([
                ('session_id', '=', session.id),
                ('payment_method_id', '=', self.id)
            ])
            
            _logger.info('Pagos OCA en sesión %s: %s', session.id, len(oca_payments))
            
            if oca_payments:
                _logger.info('Sesión POS encontrada: %s', session.id)
                return session
        
        # Si no se encuentra con pagos OCA, buscar la sesión más reciente
        # que tenga cualquier tipo de pago (fallback)
        _logger.info('No se encontró sesión con pagos OCA, buscando sesión más reciente')
        
        recent_sessions_with_payments = self.env['pos.session'].search([
            ('state', '=', 'opened'),
            ('order_ids', '!=', False)  # Sesiones que tengan pedidos
        ], order='id desc', limit=5)
        
        for session in recent_sessions_with_payments:
            _logger.info('Verificando sesión con pedidos: %s', session.id)
            
            # Verificar si tiene pedidos recientes
            recent_orders = self.env['pos.order'].search([
                ('session_id', '=', session.id)
            ], order='id desc', limit=1)
            
            if recent_orders:
                _logger.info('Sesión POS encontrada (fallback): %s', session.id)
                return session
        
        _logger.error('No se encontró ninguna sesión POS válida para la transacción: %s', transaction_id)
        return None

    @api.model
    def processFinancialPurchaseQuery(self, data, base_url_endpoint):
        """
        Consulta el estado de una transacción financiera
        
        Args:
            data (dict): Datos de la consulta
            base_url_endpoint (str): URL base del endpoint
            
        Returns:
            dict: Respuesta de la consulta
        """
        endpoint = base_url_endpoint + '/processFinancialPurchaseQuery'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)

        response_json = req.json()

        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
            '0': 'Resultado OK',
            '10': 'Aguardando por operación en el pinpad.',
            '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
            '12': 'Pinpad consultó datos (se pasó la tarjeta).',
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]
        return response_json

    def cancelFinancialPurchase(self, data):
        """
        Cancela una compra financiera
        
        Args:
            data (dict): Datos de la cancelación
            
        Returns:
            dict: Respuesta de la cancelación
        """
        self.ensure_one()
        TIMEOUT = 30

        _logger.info('cancelFinancialPurchase by user #%d:\n%s', self.env.uid, pprint.pformat(data))

        endpoint = self.sudo().url_webservice + '/cancelFinancialPurchase'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=TIMEOUT)

        response_json = req.json()

        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
            '0': 'Resultado OK',
            '10': 'Aguardando por operación en el pinpad.',
            '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
            '12': 'Pinpad consultó datos (se pasó la tarjeta).',
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
        response_json['msg'] = response_code_msg[response_json['ResponseCode']]
        _logger.info('cancelFinancialPurchase Response:\n%s', pprint.pformat(response_json))
        return response_json

    def get_ticket_number(self, refunded_ids, amount_to_send):
        """
        Obtiene el número de ticket para una devolución
        
        Args:
            refunded_ids (list): IDs de las líneas reembolsadas
            amount_to_send (float): Monto a enviar
            
        Returns:
            dict: Información del ticket
        """
        self.ensure_one()
        pos_order_line_ids = self.env['pos.order.line'].search([('id', 'in', refunded_ids)])
        payments_ids = pos_order_line_ids.mapped('order_id').mapped('payment_ids').filtered(lambda l: l.payment_method_id == self)

        if not payments_ids:
            return False

        # Find the payment with the amount closest to amount_to_send
        closest_payment_id = min(payments_ids, key=lambda p: abs(p.amount - amount_to_send))
        response = {
            'TicketNumber': closest_payment_id.ticket,
            'Acquirer': closest_payment_id.card_type,
        }
        return response

    def processFinancialPurchaseVoidByTicket(self, data, pos_session_id, account_payment_id=None):
        """
        Procesa una anulación de compra financiera por ticket.

        Args:
            data (dict): Datos de la anulación
            pos_session_id (int): ID de la sesión POS
            account_payment_id (int|None): Compatibilidad con odoo_pos_fiserv (devolución contable).

        Returns:
            dict: Respuesta de la anulación
        """
        self.ensure_one()
        if self.use_payment_terminal == 'fiserv':
            return super(PosPaymentMethod, self).processFinancialPurchaseVoidByTicket(
                data, pos_session_id, account_payment_id=account_payment_id
            )
        _logger.info('Metodo processFinancialPurchaseVoidByTicket %s', pprint.pformat(data))

        base_url_endpoint = self.sudo().url_webservice
        endpoint = base_url_endpoint + '/processFinancialPurchaseVoidByTicket'
        headers = {
            'Content-Type': 'application/json',
        }
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]

        _logger.info('processFinancialPurchaseVoidByTicket Response:\n%s', pprint.pformat(response_json))

        # Almacenar la transacción en payment.transaction SOLO cuando recibimos respuesta del POS
        # PERO solo si la respuesta es exitosa y tenemos información completa
        if response_json['ResponseCode'] == '0':
            # Solo almacenar la transacción cuando tengamos información completa
            # La información completa llega después del procesamiento en segundo plano
            pass
        else:
            # Para respuestas de error, almacenar inmediatamente
            self._store_oca_transaction(data, response_json, pos_session_id)

        pos_session_sudo = self.env["pos.session"].sudo().browse(pos_session_id)
        bus_channel_name = pos_session_sudo._get_bus_channel_name()
        id_config = pos_session_sudo.config_id.id

        if response_json['ResponseCode'] == '0':
            # Iniciar hilo para procesamiento en segundo plano
            transaction_id = response_json['TransactionId']
            threading.Thread(target=self._procesar_en_segundo_plano, args=(data, bus_channel_name, id_config, transaction_id, base_url_endpoint, pos_session_id)).start()

        return response_json

    def processFinancialReverse(self, data, base_url_endpoint):
        """
        Procesa una reversión financiera
        
        Args:
            data (dict): Datos de la reversión
            base_url_endpoint (str): URL base del endpoint
            
        Returns:
            dict: Respuesta de la reversión
        """
        self.ensure_one()

        _logger.info('processFinancialReverse by user #%d:\n%s', self.env.uid, pprint.pformat(data))

        endpoint = base_url_endpoint + '/processFinancialReverse'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
            '0': 'Resultado OK',
            '10': 'Aguardando por operación en el pinpad.',
            '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
            '12': 'Pinpad consultó datos (se pasó la tarjeta).',
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]
        _logger.info('processFinancialReverse Response:\n%s', pprint.pformat(response_json))
        return response_json

    def _resolve_itd_pos_payment_method_for_session(self, pos_session_id, pos_id_from_response):
        """
        Localiza el pos.payment.method de la sesión cuyo PosID (codigo_terminal) coincide
        con la respuesta ITD (OCA o Fiserv comparten el mismo protocolo).

        Se usa cuando el hilo de fondo llama al modelo sin recordset (p. ej. promociones)
        y no se sabe si el cobro fue por terminal OCA o Fiserv; sin esto, si el MRO
        expone primero los métodos de odoo_pos_oca, todas las ITD quedaban como OCA.

        Args:
            pos_session_id (int): Sesión POS activa.
            pos_id_from_response (str|None): PosID devuelto por el pinpad.

        Returns:
            pos.payment.method: Un registro como máximo, o recordset vacío.
        """
        if not pos_session_id or pos_id_from_response in (None, False, ''):
            return self.env['pos.payment.method']
        pos_id_norm = str(pos_id_from_response).strip()
        session = self.env['pos.session'].sudo().browse(pos_session_id)
        if not session.exists() or not session.config_id:
            return self.env['pos.payment.method']
        # --- Filtrar métodos con terminal OCA o Fiserv y mismo PosID configurado ---
        candidates = session.config_id.payment_method_ids.filtered(
            lambda m: m.use_payment_terminal in ('oca', 'fiserv')
            and (m.codigo_terminal or '').strip() == pos_id_norm
        )
        if len(candidates) > 1:
            _logger.warning(
                'ITD: varios métodos POS comparten PosID %s en config %s; se usa el primero.',
                pos_id_norm,
                session.config_id.display_name,
            )
        return candidates[:1]

    def _update_stored_transaction_with_session(
        self, transaction_id, final_result, pos_session_id, **kwargs
    ):
        """
        Actualiza la transacción almacenada con la información final del procesamiento
        o crea la transacción si no existe (respuesta completa del pinpad).

        Con odoo_pos_fiserv instalado, el ID ITD puede persistirse en
        payment.transaction como Fiserv (fiserv_transaction_id) u OCA (oca_transaction_id).
        Este método busca en ambos y, al crear, delega en Fiserv si el método POS
        coincidente con PosID es terminal Fiserv (sin tocar odoo_pos_oca_promociones).

        **kwargs: reservado (p. ej. account_payment_id en hilos Fiserv); ignorado aquí para
        no romper el MRO si algún caller pasa argumentos extra.

        Args:
            transaction_id (str): ID de transacción ITD (mismo valor en OCA y Fiserv).
            final_result (dict): Resultado final del procesamiento (payload pinpad).
            pos_session_id (int): ID de la sesión POS.
        """
        try:
            tid = str(transaction_id).strip()
            PaymentTx = self.env['payment.transaction'].sudo()

            # --- Actualización: una sola fila según dónde esté el id ITD ---
            fiserv_tx = (
                PaymentTx.search([('fiserv_transaction_id', '=', tid)], limit=1)
                if 'fiserv_transaction_id' in PaymentTx._fields
                else PaymentTx.browse()
            )
            if fiserv_tx:
                fiserv_tx.update_fiserv_transaction(final_result)
                _logger.info(
                    'Transacción Fiserv actualizada con información final (id ITD=%s)',
                    tid,
                )
                return

            oca_tx = PaymentTx.search([('oca_transaction_id', '=', tid)], limit=1)
            if oca_tx:
                oca_tx.update_oca_transaction(final_result)
                _logger.info(
                    'Transacción OCA actualizada con información final (id ITD=%s)',
                    tid,
                )
                return

            # --- Creación: _create_oca_transaction_with_complete_data enruta a Fiserv si aplica ---
            self._create_oca_transaction_with_complete_data(tid, final_result, pos_session_id)
            _logger.info(
                'Transacción ITD creada con información completa (id=%s, sesión=%s)',
                tid,
                pos_session_id,
            )

        except Exception as e:
            _logger.error('Error al actualizar/crear transacción ITD/OCA/Fiserv: %s', str(e))

    def _find_related_pos_order_by_transaction(self, transaction_id, pos_session_id):
        """
        Busca el pedido POS relacionado con una transacción.
        
        NOTA IMPORTANTE:
        Antes se usaba como fallback \"el último pedido de la sesión\", lo que
        provocaba que la transacción OCA quedara asociada a la orden anterior
        en vez de a la orden que se está creando ahora.
        
        Ahora, este método NO fuerza ninguna asociación por fallback y deja
        la transacción sin pos_order_id para que sea pos.order._associate_oca_transactions()
        quien realice la asociación definitiva una vez creada la orden POS.
        
        Args:
            transaction_id (str): ID de la transacción OCA
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.order: Recordset vacío cuando no se puede determinar con certeza
        """
        _logger.info(
            'OCA POS: _find_related_pos_order_by_transaction no aplicará fallback para transacción %s en sesión %s. '
            'La asociación se hará después desde pos.order._associate_oca_transactions.',
            transaction_id,
            pos_session_id,
        )
        return self.env['pos.order']

    def _find_related_pos_payment_by_transaction(self, transaction_id, pos_session_id):
        """
        Busca el pago POS relacionado con una transacción.
        
        Igual que con el pedido, antes se usaba como fallback \"el último pago
        OCA de la sesión\", lo que podía asociar la transacción al pago de una
        orden anterior. Esto generaba inconsistencias cuando se procesaban
        varias ventas seguidas.
        
        Ahora NO se aplica ese fallback y se deja la transacción sin
        pos_payment_id; la asociación se hará luego mediante:
        - pos.payment._associate_oca_transaction()
        - y, en promociones, la extensión en odoo_pos_oca_promociones.
        
        Args:
            transaction_id (str): ID de la transacción OCA
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.payment: Recordset vacío cuando no se puede determinar con certeza
        """
        _logger.info(
            'OCA POS: _find_related_pos_payment_by_transaction no aplicará fallback para transacción %s en sesión %s. '
            'La asociación del pago se hará después desde pos.payment._associate_oca_transaction.',
            transaction_id,
            pos_session_id,
        )
        return self.env['pos.payment'] 