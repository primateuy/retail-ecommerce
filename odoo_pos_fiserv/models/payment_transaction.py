# -*- coding: utf-8 -*-
"""
Modelo para extender payment.transaction con campos específicos de Fiserv ITD

Este módulo proporciona la funcionalidad para almacenar y gestionar
transacciones de pago específicas del sistema Fiserv ITD, incluyendo
campos adicionales y métodos de creación y actualización.
"""

from odoo import fields, models, api
from odoo.exceptions import ValidationError
import logging
import json

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


class PaymentTransaction(models.Model):
    """
    Extensión del modelo payment.transaction para Fiserv ITD.

    Agrega campos para datos del pinpad, auditoría JSON y relación con pedidos POS.
    como información de tarjetas, códigos de autorización, números de ticket,
    y relaciones con pedidos y pagos POS.
    """
    _inherit = 'payment.transaction'

    # Campos específicos de Fiserv ITD
    pos_id = fields.Char(
        string='POS ID',
        help='Identificador del punto de venta (PosID)'
    )
    
    card_bin = fields.Char(
        string='BIN de Tarjeta',
        help='Primeros 6 números de la tarjeta'
    )
    
    card_last_four = fields.Char(
        string='Últimos 4 dígitos',
        help='Últimos 4 dígitos de la tarjeta'
    )
    
    issuer_code = fields.Char(
        string='Código del Emisor',
        help='Código del emisor de la tarjeta'
    )
    
    issuer_name = fields.Char(
        string='Nombre del Emisor',
        help='Nombre del emisor de la tarjeta'
    )
    
    installments = fields.Integer(
        string='Cantidad de Cuotas',
        help='Número de cuotas de la transacción'
    )
    
    acquirer = fields.Char(
        string='Adquirente',
        help='Proveedor de pago (Acquirer)'
    )
    
    ticket_number = fields.Char(
        string='Número de Ticket',
        help='Número de ticket de la transacción'
    )
    
    batch_number = fields.Char(
        string='Número de Lote',
        help='Número de lote de la transacción'
    )
    
    authorization_code = fields.Char(
        string='Código de Autorización',
        help='Código de autorización de la transacción'
    )
    
    transaction_origin = fields.Selection([
        ('pos_payment', 'Pago POS'),
        ('pos_order', 'Pedido POS'),
        ('other', 'Otro')
    ], string='Origen de Transacción', default='pos_payment')
    
    pos_order_id = fields.Many2one(
        'pos.order',
        string='Pedido POS',
        help='Pedido del punto de venta que generó la transacción'
    )
    
    pos_payment_id = fields.Many2one(
        'pos.payment',
        string='Pago POS',
        help='Pago del punto de venta que generó la transacción'
    )
    
    is_promotion = fields.Boolean(
        string='Es Promoción',
        help='Indica si la transacción es una promoción'
    )
    
    merchant_number = fields.Char(
        string='Número de Comercio',
        help='Número de comercio para el adquirente'
    )
    
    invoice_number = fields.Char(
        string='Número de Factura',
        help='Número de factura enviado al POS'
    )
    
    # Campos de auditoría
    fiserv_transaction_id = fields.Char(
        string='ID transacción ITD',
        help='TransactionId asignado por Fiserv ITD.',
    )

    fiserv_response_code = fields.Char(
        string='Código de respuesta ITD',
        help='ResponseCode de la consulta o respuesta final.',
    )

    fiserv_response_message = fields.Text(
        string='Mensaje de respuesta',
        help='Texto descriptivo para el usuario o soporte.',
    )
    
    # Campo para almacenar la respuesta completa del POS
    fiserv_complete_response = fields.Text(
        string='Respuesta Completa del POS',
        help='Respuesta completa del POS en formato JSON para auditoría'
    )

    @staticmethod
    def _parse_itd_quota(val):
        """
        Normaliza el campo Quota devuelto por ITD (entero o texto con ceros a la izquierda).

        Args:
            val: Valor crudo de la respuesta.

        Returns:
            int: Número de cuotas o 0 si no es parseable.
        """
        try:
            return int(str(val).strip() or 0)
        except (TypeError, ValueError):
            return 0

    def write(self, vals):
        """
        Sobrescribe el método write para actualizar el campo payment_transaction_id
        en el pago cuando se asocie una transacción
        
        Args:
            vals (dict): Valores a escribir
            
        Returns:
            bool: True si se escribió correctamente
        """
        # Si se está actualizando pos_payment_id, actualizar el campo correspondiente en el pago
        if 'pos_payment_id' in vals:
            # Obtener el pago anterior y nuevo
            old_payment_id = self.pos_payment_id.id if self.pos_payment_id else False
            new_payment_id = vals['pos_payment_id']
            
            # Si había un pago anterior, limpiar su campo payment_transaction_id
            if old_payment_id:
                old_payment = self.env['pos.payment'].browse(old_payment_id)
                if old_payment.exists():
                    old_payment.payment_transaction_id = False
            
            # Si hay un nuevo pago, actualizar su campo payment_transaction_id
            if new_payment_id:
                new_payment = self.env['pos.payment'].browse(new_payment_id)
                if new_payment.exists():
                    new_payment.payment_transaction_id = self.id
        
        # Llamar al método write original
        return super(PaymentTransaction, self).write(vals)

    def _create_payment(self, **extra_create_values):
        """
        Sobrescribe el método de account_payment para NO crear account.payment en
        transacciones que provienen del POS Fiserv ITD.

        En ventas POS Fiserv el cobro ya está representado por pos.payment; si además
        se creara un account.payment (el que se ve como "Online Payment" en la UI),
        quedaría un pago extra asociado a la orden y a la transacción, lo cual es
        incorrecto. Para transacciones con origen pos_payment o pos_order no se
        debe crear account.payment.

        Al probar: revisar logs con "Fiserv POS: omitiendo creación de account.payment"
        y verificar que en la orden/transacción no aparezca un pago extra de
        contabilidad (solo debe existir el pos.payment).
        """
        self.ensure_one()
        # Identificar transacciones que provienen del POS Fiserv (no crear account.payment)
        is_pos_fiserv = (
            self.transaction_origin in ('pos_payment', 'pos_order')
            or bool(self.pos_payment_id)
        )
        if is_pos_fiserv:
            _logger.info(
                'Fiserv POS: omitiendo creación de account.payment para transacción %s '
                '(reference=%s, pos_order_id=%s, pos_payment_id=%s). '
                'El cobro ya está registrado en pos.payment.',
                self.fiserv_transaction_id or self.reference,
                self.reference,
                self.pos_order_id.id if self.pos_order_id else None,
                self.pos_payment_id.id if self.pos_payment_id else None,
            )
            # Retornar recordset vacío; el flujo estándar no crea pago para esta transacción
            return self.env['account.payment']
        # Para transacciones que no son POS Fiserv (ej. portal/ecommerce), comportamiento estándar
        return super(PaymentTransaction, self)._create_payment(**extra_create_values)

    @api.model
    def create_fiserv_transaction(self, pos_data, itd_response, pos_order=None, pos_payment=None):
        """
        Crea una nueva transacción Fiserv con la información recibida del POS
        
        Args:
            pos_data (dict): Datos enviados al POS
            itd_response (dict): Respuesta recibida del POS
            pos_order (pos.order): Pedido POS relacionado
            pos_payment (pos.payment): Pago POS relacionado
            
        Returns:
            payment.transaction: Transacción creada
        """
        # Determinar el estado de la transacción basado en la respuesta
        # ITD puede enviar ResponseCode como int (p. ej. 0).
        response_code = str(itd_response.get('ResponseCode', '999')).strip()
        state = self._get_transaction_state_from_response(response_code)
        
        # Convertir el monto desde centavos a la unidad correcta
        # El POS envía el monto multiplicado por 100 (centavos sin separador), se normaliza aquí
        amount_from_pos = pos_data.get('Amount', 0.0)
        if isinstance(amount_from_pos, str):
            try:
                amount_from_pos = float(amount_from_pos)
            except (ValueError, TypeError):
                amount_from_pos = 0.0
        
        # Convertir desde centavos a la unidad correcta
        corrected_amount = amount_from_pos / 100.0 if amount_from_pos > 0 else 0.0
        
        # Log para debuggear el problema del monto
        _logger.info('Fiserv Transaction Amount Debug - Original: %s, Corrected: %s', 
                    amount_from_pos, corrected_amount)
        
        # Obtener el número de factura del pedido POS
        invoice_number = self._get_invoice_number_from_relations(pos_order, pos_payment)

        # ITD puede devolver Issuer como entero o como dict según fase de la respuesta
        iss = itd_response.get('Issuer')
        if isinstance(iss, dict):
            issuer_code = str(iss.get('code', '') or '')
            issuer_name = str(iss.get('name', '') or '')
        elif iss is not None and iss != '':
            issuer_code = str(iss)
            issuer_name = self._get_fiserv_issuer_name(iss)
        else:
            issuer_code = ''
            issuer_name = ''

        # Crear valores para la transacción
        transaction_vals = {
            'provider_id': self._get_fiserv_provider_id(),
            'payment_method_id': self._get_fiserv_payment_method_id(),
            'reference': self._generate_fiserv_reference(pos_data, itd_response),
            'amount': corrected_amount,
            'currency_id': self._get_currency_id(pos_data),
            'state': state,
            'state_message': itd_response.get('msg', ''),
            'partner_id': self._get_partner_id(pos_order, pos_payment),
            'company_id': self._get_company_id(pos_order, pos_payment),
            
            # Campos específicos de Fiserv ITD
            'pos_id': pos_data.get('PosID'),
            'card_bin': itd_response.get('CardNumber', '')[:6] if itd_response.get('CardNumber') else '',
            'card_last_four': itd_response.get('CardNumber', '')[-4:] if itd_response.get('CardNumber') else '',
            'issuer_code': issuer_code,
            'issuer_name': issuer_name,
            'installments': pos_data.get('Installments', 1),
            'acquirer': itd_response.get('Acquirer', ''),
            'ticket_number': itd_response.get('Ticket', ''),
            'batch_number': itd_response.get('Batch', ''),
            'authorization_code': itd_response.get('AuthorizationCode', ''),
            'merchant_number': itd_response.get('Merchant', ''),
            'invoice_number': invoice_number,
            'fiserv_transaction_id': (
                str(itd_response.get('TransactionId')).strip()
                if itd_response.get('TransactionId') is not None
                else ''
            ),
            'fiserv_response_code': response_code,
            'fiserv_response_message': itd_response.get('msg', ''),
            'fiserv_complete_response': json.dumps(itd_response, indent=2, ensure_ascii=False),
            
            # Campos de relación
            'pos_order_id': pos_order.id if pos_order else False,
            'pos_payment_id': pos_payment.id if pos_payment else False,
            'transaction_origin': 'pos_payment' if pos_payment else 'pos_order' if pos_order else 'other',
        }
        
        # Crear la transacción
        transaction = self.create(transaction_vals)
        
        # Si hay un pago POS asociado, actualizar su campo payment_transaction_id
        if pos_payment:
            pos_payment.payment_transaction_id = transaction.id
        
        return transaction
    
    def _get_transaction_state_from_response(self, response_code):
        """
        Determina el estado según ResponseCode ITD.

        Args:
            response_code (str): Código de respuesta (stringificado)
            
        Returns:
            str: Estado de la transacción
        """
        success_codes = ['0']
        pending_codes = ['10', '12']
        error_codes = ['100', '101', '102', '103', '104', '105', '106', '107', '108', '109', 
                      '110', '111', '112', '113', '999', '-100']
        
        if response_code in success_codes:
            return 'done'
        elif response_code in pending_codes:
            return 'pending'
        elif response_code in error_codes:
            return 'error'
        else:
            return 'error'
    
    @api.model
    def get_fiserv_display_message(self, itd_response):
        """
        Obtiene el mensaje legible para el usuario según ResponseCode y posResponseCode
        (Anexos 1 y 2 POSLink v135). Prioriza el código del terminal cuando indica rechazo.
        
        Args:
            itd_response (dict): Respuesta del POS (ResponseCode, PosResponseCode/posResponseCode, msg)
            
        Returns:
            str: Mensaje en español para mostrar al usuario
        """
        if not itd_response:
            return 'Error desconocido'
        # Código del terminal (puede venir como PosResponseCode o posResponseCode)
        pos_code = itd_response.get('PosResponseCode') or itd_response.get('posResponseCode')
        pos_response_code = (
            str(pos_code).strip().upper()
            if pos_code is not None and pos_code != ''
            else None
        )
        response_code = str(itd_response.get('ResponseCode', '')).strip()
        
        # Si el terminal devolvió un código de rechazo, usar mensaje del Anexo 2
        if pos_response_code and pos_response_code not in POS_APPROVED_CODES:
            return POS_RESPONSE_CODE_MESSAGES.get(
                pos_response_code,
                f'Rechazada por el terminal (código {pos_response_code})',
            )
        # Si ResponseCode del PLS no es éxito, usar mensaje del Anexo 1
        if response_code and response_code not in ('0',):
            return RESPONSE_CODE_MESSAGES.get(
                response_code,
                f'Error del sistema POSLink (código {response_code})',
            )
        # Aprobado: usar mensaje que venga en la respuesta o genérico
        return itd_response.get('msg', '') or 'Aprobado'
    
    def _get_transaction_state_with_pos_response(self, response_code, itd_response):
        """
        Determina el estado considerando ResponseCode y posResponseCode.
        Si el terminal rechazó (posResponseCode no aprobado), estado = error.
        
        Args:
            response_code (str): ResponseCode del PLS
            itd_response (dict): Respuesta completa
            
        Returns:
            str: 'done', 'pending' o 'error'
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
    
    def _get_fiserv_provider_id(self):
        """
        Obtiene el ID del proveedor Fiserv existente
        
        Returns:
            int: ID del proveedor Fiserv
        """
        provider = self.env['payment.provider'].search([('code', '=', 'fiserv')], limit=1)
        if not provider:
            _logger.error('No se encontró el proveedor de pago Fiserv. Configúrelo en Contabilidad / Pagos en línea.')
            # Retornar un ID por defecto para evitar errores
            return 1
        return provider.id
    
    def _get_fiserv_payment_method_id(self):
        """
        Obtiene el ID del método de pago Fiserv existente
        
        Returns:
            int: ID del método de pago Fiserv
        """
        payment_method = self.env['payment.method'].search([('code', '=', 'fiserv')], limit=1)
        if not payment_method:
            _logger.error('No se encontró el método de pago Fiserv. Asegúrese de que esté configurado.')
            # Retornar un ID por defecto para evitar errores
            return 1
        return payment_method.id
    
    def _generate_fiserv_reference(self, pos_data, itd_response):
        """
        Genera una referencia única para la transacción Fiserv
        
        Args:
            pos_data (dict): Datos enviados al POS
            itd_response (dict): Respuesta recibida del POS
            
        Returns:
            str: Referencia única
        """
        _tid = itd_response.get('TransactionId', '')
        transaction_id = str(_tid).strip() if _tid is not None and _tid != '' else ''
        pos_id = pos_data.get('PosID', '')
        timestamp = pos_data.get('TransactionDateTimeyyyyMMddHHmmssSSS', '')
        
        return f"FISERV-{pos_id}-{transaction_id}-{timestamp}"
    
    def _get_currency_id(self, pos_data):
        """
        Obtiene el ID de la moneda
        
        Args:
            pos_data (dict): Datos enviados al POS
            
        Returns:
            int: ID de la moneda
        """
        # Por defecto usar la moneda de la empresa
        return self.env.company.currency_id.id
    
    def _get_partner_id(self, pos_order, pos_payment):
        """
        Obtiene el ID del partner
        
        Args:
            pos_order (pos.order): Pedido POS
            pos_payment (pos.payment): Pago POS
            
        Returns:
            int: ID del partner
        """
        if pos_order and pos_order.partner_id:
            return pos_order.partner_id.id
        elif pos_payment and pos_payment.partner_id:
            return pos_payment.partner_id.id
        else:
            # Partner por defecto
            return self.env.ref('base.partner_demo').id if self.env.ref('base.partner_demo', raise_if_not_found=False) else 1
    
    def _get_company_id(self, pos_order, pos_payment):
        """
        Obtiene el ID de la empresa
        
        Args:
            pos_order (pos.order): Pedido POS
            pos_payment (pos.payment): Pago POS
            
        Returns:
            int: ID de la empresa
        """
        if pos_order and pos_order.company_id:
            return pos_order.company_id.id
        elif pos_payment and pos_payment.company_id:
            return pos_payment.company_id.id
        else:
            return self.env.company.id
    
    def update_fiserv_transaction(self, itd_response):
        """
        Actualiza una transacción Fiserv existente con nueva información.
        Usa mensaje parseado según POSLink v135 y considera posResponseCode para estado error.
        
        Args:
            itd_response (dict): Nueva respuesta del POS
        """
        response_code = str(itd_response.get('ResponseCode', '999')).strip()
        new_state = self._get_transaction_state_with_pos_response(response_code, itd_response)
        state_message = self.get_fiserv_display_message(itd_response)
        update_vals = {
            'state': new_state,
            'state_message': state_message,
            'fiserv_response_code': response_code,
            'fiserv_response_message': state_message,
            'fiserv_complete_response': json.dumps(itd_response, indent=2, ensure_ascii=False),
        }
        
        # Actualizar campos específicos si están disponibles en la respuesta
        if itd_response.get('CardNumber'):
            update_vals.update({
                'card_bin': itd_response['CardNumber'][:6],
                'card_last_four': itd_response['CardNumber'][-4:],
            })
        
        if itd_response.get('Issuer'):
            if isinstance(itd_response['Issuer'], dict):
                update_vals.update({
                    'issuer_code': itd_response['Issuer'].get('code', ''),
                    'issuer_name': itd_response['Issuer'].get('name', ''),
                })
        
        if itd_response.get('Acquirer'):
            update_vals['acquirer'] = itd_response['Acquirer']
        
        if itd_response.get('Ticket'):
            update_vals['ticket_number'] = itd_response['Ticket']
        
        if itd_response.get('Batch'):
            update_vals['batch_number'] = itd_response['Batch']
        
        if itd_response.get('AuthorizationCode'):
            update_vals['authorization_code'] = itd_response['AuthorizationCode']
        
        if itd_response.get('Merchant'):
            update_vals['merchant_number'] = itd_response['Merchant']
        
        self.write(update_vals)
    
    @api.model
    def create_fiserv_transaction_with_complete_data(self, itd_response, pos_order=None, pos_payment=None, transaction_id=None):
        """
        Crea una nueva transacción Fiserv con la información completa recibida del POS
        
        Args:
            itd_response (dict): Respuesta completa del POS
            pos_order (pos.order): Pedido POS relacionado
            pos_payment (pos.payment): Pago POS relacionado
            transaction_id (str): ID de la transacción Fiserv
            
        Returns:
            payment.transaction: Transacción creada
        """
        # Determinar el estado considerando ResponseCode y posResponseCode (rechazo = error)
        response_code = str(itd_response.get('ResponseCode', '999')).strip()
        state = self._get_transaction_state_with_pos_response(response_code, itd_response)
        state_message = self.get_fiserv_display_message(itd_response)
        
        # Obtener el monto desde la respuesta del POS
        total_amount = itd_response.get('TotalAmount', '0')
        if isinstance(total_amount, str):
            try:
                total_amount = float(total_amount)
            except (ValueError, TypeError):
                total_amount = 0.0
        
        # Convertir desde centavos a la unidad correcta
        corrected_amount = total_amount / 100.0 if total_amount > 0 else 0.0
        
        # Log para debuggear el problema del monto
        _logger.info('Fiserv Complete Transaction Amount Debug - TotalAmount: %s, Corrected: %s', 
                    total_amount, corrected_amount)
        
        # Obtener el número de factura del pedido POS relacionado
        invoice_number = self._get_invoice_number_from_relations(pos_order, pos_payment)
        
        # Log para debuggear la referencia y número de factura
        _logger.info('Fiserv Invoice Number Debug - Invoice Number: %s, POS Order: %s, POS Payment: %s', 
                    invoice_number, pos_order.name if pos_order else 'None', pos_payment.name if pos_payment else 'None')
        
        # ITD puede devolver TransactionId numérico; el campo Odoo es Char.
        _merge_tid = (
            transaction_id
            if transaction_id not in (None, False, '')
            else itd_response.get('TransactionId')
        )
        _fiserv_tid_str = (
            str(_merge_tid).strip()
            if _merge_tid is not None and _merge_tid != ''
            else ''
        )

        # Crear valores para la transacción con información completa
        transaction_vals = {
            'provider_id': self._get_fiserv_provider_id(),
            'payment_method_id': self._get_fiserv_payment_method_id(),
            'reference': self._generate_fiserv_reference_from_complete_data(itd_response),
            'amount': corrected_amount,
            'currency_id': self._get_currency_id_from_response(itd_response),
            'state': state,
            'state_message': state_message,
            'partner_id': self._get_partner_id(pos_order, pos_payment),
            'company_id': self._get_company_id(pos_order, pos_payment),
            
            # Campos específicos de Fiserv ITD con información completa
            'pos_id': itd_response.get('PosID'),
            'card_bin': itd_response.get('CardNumber', '')[:6] if itd_response.get('CardNumber') else '',
            'card_last_four': itd_response.get('CardNumber', '')[-4:] if itd_response.get('CardNumber') else '',
            'issuer_code': str(itd_response.get('Issuer', '')),
            'issuer_name': self._get_fiserv_issuer_name(itd_response.get('Issuer')),
            'installments': self._parse_itd_quota(itd_response.get('Quota', 0)),
            'acquirer': str(itd_response.get('Acquirer', '')),
            'ticket_number': itd_response.get('Ticket', ''),
            'batch_number': itd_response.get('Batch', ''),
            'authorization_code': itd_response.get('AuthorizationCode', ''),
            'merchant_number': itd_response.get('Merchant', ''),
            'invoice_number': invoice_number,
            'fiserv_transaction_id': _fiserv_tid_str,
            'fiserv_response_code': response_code,
            'fiserv_response_message': state_message,
            'fiserv_complete_response': json.dumps(itd_response, indent=2, ensure_ascii=False),
            
            # Campos de relación
            'pos_order_id': pos_order.id if pos_order else False,
            'pos_payment_id': pos_payment.id if pos_payment else False,
            'transaction_origin': 'pos_payment' if pos_payment else 'pos_order' if pos_order else 'other',
        }
        
        # Crear la transacción
        transaction = self.create(transaction_vals)
        
        # Si hay un pago POS asociado, actualizar su campo payment_transaction_id
        if pos_payment:
            pos_payment.payment_transaction_id = transaction.id
        
        return transaction
    
    def _generate_fiserv_reference_from_complete_data(self, itd_response):
        """
        Genera una referencia única para la transacción Fiserv con información completa
        
        Args:
            itd_response (dict): Respuesta completa del POS
            
        Returns:
            str: Referencia única
        """
        pos_id = itd_response.get('PosID', '')
        ticket = itd_response.get('Ticket', '')
        batch = itd_response.get('Batch', '')
        authorization = itd_response.get('AuthorizationCode', '')
        transaction_date = itd_response.get('TransactionDate', '')
        transaction_hour = itd_response.get('TransactionHour', '')
        
        # Crear una referencia más completa y única
        reference_parts = [
            'FISERV',
            pos_id,
            ticket,
            batch,
            authorization,
            transaction_date,
            transaction_hour
        ]
        
        # Filtrar partes vacías y unir
        reference = '-'.join([part for part in reference_parts if part])
        
        # Si la referencia está vacía, usar un fallback
        if not reference:
            reference = f"FISERV-{pos_id}-{ticket}-{batch}"
        
        _logger.info('Fiserv Reference Generated: %s', reference)
        return reference
    
    def _get_currency_id_from_response(self, itd_response):
        """
        Obtiene el ID de la moneda desde la respuesta del POS
        
        Args:
            itd_response (dict): Respuesta del POS
            
        Returns:
            int: ID de la moneda
        """
        currency_code = itd_response.get('Currency', '858')
        
        # Mapear códigos de moneda ITD a monedas de Odoo
        currency_mapping = {
            '858': 'UYU',  # Peso Uruguayo
            '840': 'USD',  # Dólar Estadounidense
        }
        
        currency_name = currency_mapping.get(currency_code, 'UYU')
        currency = self.env['res.currency'].search([('name', '=', currency_name)], limit=1)
        
        if currency:
            return currency.id
        
        # Por defecto usar la moneda de la empresa
        return self.env.company.currency_id.id
    
    def _get_fiserv_issuer_name(self, issuer_code):
        """
        Obtiene el nombre del emisor basado en el código
        
        Args:
            issuer_code (int/str): Código del emisor
            
        Returns:
            str: Nombre del emisor
        """
        # Mapeo parcial de códigos ITD Issuer a nombres legibles (tabla mixta Fiserv).
        # Código 21 = red/emisor OCA en Uruguay (nombre comercial en la respuesta ITD).
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
            # Buscar el método de pago correspondiente en Odoo
            payment_method = self.env['payment.method'].search([
                ('name', 'ilike', mapped_name)
            ], limit=1)
            
            if payment_method:
                return payment_method.name
        
        # Si no se encuentra, usar el mapeo directo o el código
        return mapped_name or f'Emisor {issuer_code}'

    def _get_invoice_number_from_relations(self, pos_order, pos_payment):
        """
        Obtiene el número de factura del pedido POS relacionado
        
        Args:
            pos_order (pos.order): Pedido POS
            pos_payment (pos.payment): Pago POS
            
        Returns:
            str: Número de factura
        """
        # Intentar obtener el número de pedido del punto de venta
        if pos_order:
            # Usar el número del pedido POS
            if pos_order.name:
                return pos_order.name
            # Si no tiene nombre, usar el ID
            else:
                return f"POS-{pos_order.id}"
        
        # Si no hay pedido, intentar con el pago POS
        elif pos_payment:
            # El pago POS no tiene invoice_id, usar el número del pedido asociado
            if pos_payment.pos_order_id:
                if pos_payment.pos_order_id.name:
                    return pos_payment.pos_order_id.name
                else:
                    return f"POS-{pos_payment.pos_order_id.id}"
            # Si no tiene pedido asociado, usar el número del pago
            elif pos_payment.name:
                return pos_payment.name
            # Si no tiene nombre, usar el ID
            else:
                return f"PAY-{pos_payment.id}"
        
        # Si no hay relaciones, usar un valor por defecto
        else:
            return 'Sin factura'
    
    def update_payment_transaction_reference(self):
        """
        Actualiza el campo payment_transaction_id en el pago POS asociado
        
        Este método se ejecuta cuando se asocia una transacción a un pago
        para mantener la referencia bidireccional entre pago y transacción.
        """
        for transaction in self:
            if transaction.pos_payment_id:
                # Actualizar el campo payment_transaction_id en el pago
                transaction.pos_payment_id.payment_transaction_id = transaction.id
                _logger.info('Campo payment_transaction_id actualizado en pago %s para transacción %s', 
                           transaction.pos_payment_id.name, transaction.fiserv_transaction_id) 