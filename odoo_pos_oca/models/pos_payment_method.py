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


    def enviar_pago(self, data, pos_session_id, has_refunded_line):
        self.ensure_one()
        if not has_refunded_line:
            return self.processFinancialPurchase(data, pos_session_id)

        return self.processFinancialPurchaseVoidByTicket(data, pos_session_id)

    def processFinancialPurchase(self, data, pos_session_id):
        """
        Procesa una compra financiera enviando datos al POS y almacenando la transacción
        
        Args:
            data (dict): Datos de la transacción a enviar al POS
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            dict: Respuesta del POS
        """
        self.ensure_one()
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
                
                # Si no se encuentra por tracking_number, intentar por ID del pedido
                try:
                    order_id = int(invoice_number)
                    _logger.info('Intentando buscar por ID del pedido: %s', order_id)
                    
                    pos_order = self.env['pos.order'].search([
                        ('id', '=', order_id),
                        ('session_id', '=', pos_session_id)
                    ], limit=1)
                    
                    if pos_order:
                        _logger.info('Pedido POS encontrado por ID: %s (InvoiceNumber: %s)', pos_order.name, invoice_number)
                        return pos_order
                    else:
                        _logger.warning('No se encontró pedido con ID %s en sesión %s', order_id, pos_session_id)
                        
                except (ValueError, TypeError) as e:
                    _logger.warning('Error al convertir InvoiceNumber a ID: %s', str(e))
            
            # Si no se encuentra por InvoiceNumber, buscar el pedido más reciente como fallback
            _logger.info('No se encontró pedido por InvoiceNumber, buscando el más reciente')
            pos_order = self.env['pos.order'].search([
                ('session_id', '=', pos_session_id)
            ], order='id desc', limit=1)
            
            if pos_order:
                _logger.info('Pedido POS encontrado (fallback): %s', pos_order.name)
            
            return pos_order
            
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

    def _procesar_en_segundo_plano(self, data, bus_channel_name, id_config, transaction_id, base_url_endpoint, pos_session_id):
        """
        Procesa la transacción en segundo plano y actualiza la información almacenada
        
        Args:
            data (dict): Datos originales de la transacción
            bus_channel_name (str): Nombre del canal de bus
            id_config (int): ID de la configuración
            transaction_id (str): ID de la transacción
            base_url_endpoint (str): URL base del endpoint
            pos_session_id (int): ID de la sesión POS
        """
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

            while True:
                sleep(4)
                _logger.info('>>>Intento>>>')
                try:
                    result = env['pos.payment.method'].processFinancialPurchaseQuery(data, base_url_endpoint)
                    _logger.info('Result: %s', pprint.pformat(result))

                    response_code = result['ResponseCode']
                    rt = result['RemainingExpirationTime'] if 'RemainingExpirationTime' in result else False
                    if response_code not in ['10', '12']:
                        break

                    if response_code in ['10', '12'] and rt and rt == 0.0:
                        self.processFinancialReverse(data, base_url_endpoint)

                except Exception as e:
                    _logger.error('Error en procesamiento en segundo plano: %s', str(e))
                    break
                _logger.info('>>>FIN Intento>>>')

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

    def _create_oca_transaction_with_complete_data(self, transaction_id, final_result, pos_session_id=None):
        """
        Crea una transacción OCA con la información completa del POS
        
        Args:
            transaction_id (str): ID de la transacción OCA
            final_result (dict): Resultado final con información completa
            pos_session_id (int): ID de la sesión POS (opcional)
        """
        try:
            _logger.info('Creando transacción OCA con información completa para ID: %s', transaction_id)
            
            pos_session = None
            pos_order = None
            pos_payment = None
            
            if pos_session_id:
                # Usar directamente el ID de la sesión si está disponible
                pos_session = self.env['pos.session'].browse(pos_session_id)
                if pos_session.exists():
                    _logger.info('Usando sesión POS proporcionada: %s', pos_session_id)
                    pos_order = self._find_related_pos_order_by_transaction(transaction_id, pos_session_id)
                    pos_payment = self._find_related_pos_payment_by_transaction(transaction_id, pos_session_id)
                else:
                    _logger.warning('Sesión POS %s no existe, buscando alternativas', pos_session_id)
                    pos_session = None
            
            if not pos_session:
                # Buscar el pedido POS relacionado usando el transaction_id
                pos_session = self._find_session_by_transaction_id(transaction_id)
                
                if not pos_session:
                    _logger.warning('No se encontró sesión POS para la transacción: %s. Creando transacción sin relaciones.', transaction_id)
                    # Crear la transacción sin relaciones específicas
                    self.env['payment.transaction'].sudo().create_oca_transaction_with_complete_data(
                        oca_response=final_result,
                        pos_order=None,
                        pos_payment=None,
                        transaction_id=transaction_id
                    )
                    return
                
                # Buscar el pedido POS relacionado
                pos_order = self._find_related_pos_order_by_transaction(transaction_id, pos_session.id)
                pos_payment = self._find_related_pos_payment_by_transaction(transaction_id, pos_session.id)
            
            _logger.info('Relaciones encontradas - Sesión: %s, Pedido: %s, Pago: %s', 
                        pos_session.id, pos_order.id if pos_order else 'None', pos_payment.id if pos_payment else 'None')
            
            # Crear la transacción con información completa
            transaction = self.env['payment.transaction'].sudo().create_oca_transaction_with_complete_data(
                oca_response=final_result,
                pos_order=pos_order,
                pos_payment=pos_payment,
                transaction_id=transaction_id
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
                    transaction_id=transaction_id
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

    def processFinancialPurchaseVoidByTicket(self, data, pos_session_id):
        """
        Procesa una anulación de compra financiera por ticket
        
        Args:
            data (dict): Datos de la anulación
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            dict: Respuesta de la anulación
        """
        self.ensure_one()
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

    def _update_stored_transaction_with_session(self, transaction_id, final_result, pos_session_id):
        """
        Actualiza la transacción almacenada con la información final del procesamiento
        O crea la transacción si no existe (cuando tenemos información completa)
        
        Args:
            transaction_id (str): ID de la transacción OCA
            final_result (dict): Resultado final del procesamiento
            pos_session_id (int): ID de la sesión POS
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
                self._create_oca_transaction_with_complete_data(transaction_id, final_result, pos_session_id)
                _logger.info('Transacción OCA creada exitosamente con información completa')
                
        except Exception as e:
            _logger.error('Error al actualizar/crear transacción OCA: %s', str(e))

    def _find_related_pos_order_by_transaction(self, transaction_id, pos_session_id):
        """
        Busca el pedido POS relacionado con una transacción
        
        Args:
            transaction_id (str): ID de la transacción OCA
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.order: Pedido POS encontrado o None
        """
        # Buscar el pedido más reciente en la sesión
        pos_order = self.env['pos.order'].search([
            ('session_id', '=', pos_session_id)
        ], order='id desc', limit=1)
        
        return pos_order

    def _find_related_pos_payment_by_transaction(self, transaction_id, pos_session_id):
        """
        Busca el pago POS relacionado con una transacción
        
        Args:
            transaction_id (str): ID de la transacción OCA
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.payment: Pago POS encontrado o None
        """
        # Buscar el pago OCA más reciente en la sesión
        pos_payment = self.env['pos.payment'].search([
            ('session_id', '=', pos_session_id),
            ('payment_method_id', '=', self.id)
        ], order='id desc', limit=1)
        
        return pos_payment 