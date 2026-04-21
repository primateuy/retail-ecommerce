# -*- coding: utf-8 -*-
"""
Modelo para extender payment.transaction con campos específicos de OCA

Este módulo proporciona la funcionalidad para almacenar y gestionar
transacciones de pago específicas del sistema OCA, incluyendo
campos adicionales y métodos de creación y actualización.
"""

from odoo import fields, models, api
from odoo.exceptions import ValidationError
import logging
import json
import uuid

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

# Códigos aprobados del terminal (Anexo 2 - posResponseCode). Cualquier otro código = rechazo/error.
POS_APPROVED_CODES = ('00', '08', '10', '11', '85', 'OF')

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
    Extensión del modelo payment.transaction para almacenar información específica de OCA
    
    Agrega campos adicionales para almacenar datos específicos del sistema OCA
    como información de tarjetas, códigos de autorización, números de ticket,
    y relaciones con pedidos y pagos POS.
    """
    _inherit = 'payment.transaction'

    # Campos específicos de OCA
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
        ('account_payment', 'Pago contable'),
        ('other', 'Otro'),
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
    oca_transaction_id = fields.Char(
        string='ID Transacción OCA',
        help='ID interno de la transacción OCA'
    )
    
    oca_response_code = fields.Char(
        string='Código de Respuesta OCA',
        help='Código de respuesta del sistema OCA'
    )
    
    oca_response_message = fields.Text(
        string='Mensaje de Respuesta OCA',
        help='Mensaje de respuesta del sistema OCA'
    )
    
    # Campo para almacenar la respuesta completa del POS
    oca_complete_response = fields.Text(
        string='Respuesta Completa del POS',
        help='Respuesta completa del POS en formato JSON para auditoría'
    )
    
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
        transacciones que provienen del POS OCA.

        En ventas POS OCA el cobro ya está representado por pos.payment; si además
        se creara un account.payment (el que se ve como "Online Payment" en la UI),
        quedaría un pago extra asociado a la orden y a la transacción, lo cual es
        incorrecto. Para transacciones con origen pos_payment o pos_order no se
        debe crear account.payment.

        Al probar: revisar logs con "OCA POS: omitiendo creación de account.payment"
        y verificar que en la orden/transacción no aparezca un pago extra de
        contabilidad (solo debe existir el pos.payment).
        """
        self.ensure_one()
        # Coexistencia con Fiserv: pago contable ya existe (campo definido en odoo_pos_fiserv).
        if (
            self.transaction_origin == 'account_payment'
            and getattr(self, 'account_payment_id', False)
        ):
            return self.account_payment_id

        # Identificar transacciones que provienen del POS OCA (no crear account.payment)
        is_pos_oca = (
            self.transaction_origin in ('pos_payment', 'pos_order')
            or bool(self.pos_payment_id)
        )
        if is_pos_oca:
            _logger.info(
                'OCA POS: omitiendo creación de account.payment para transacción %s '
                '(reference=%s, pos_order_id=%s, pos_payment_id=%s). '
                'El cobro ya está registrado en pos.payment.',
                self.oca_transaction_id or self.reference,
                self.reference,
                self.pos_order_id.id if self.pos_order_id else None,
                self.pos_payment_id.id if self.pos_payment_id else None,
            )
            # Retornar recordset vacío; el flujo estándar no crea pago para esta transacción
            return self.env['account.payment']
        # Para transacciones que no son POS OCA (ej. portal/ecommerce), comportamiento estándar
        return super(PaymentTransaction, self)._create_payment(**extra_create_values)

    @api.model
    def create_oca_transaction(self, pos_data, oca_response, pos_order=None, pos_payment=None):
        """
        Crea una nueva transacción OCA con la información recibida del POS
        
        Args:
            pos_data (dict): Datos enviados al POS
            oca_response (dict): Respuesta recibida del POS
            pos_order (pos.order): Pedido POS relacionado
            pos_payment (pos.payment): Pago POS relacionado
            
        Returns:
            payment.transaction: Transacción creada
        """
        # Determinar el estado de la transacción basado en la respuesta
        response_code = oca_response.get('ResponseCode', '999')
        state = self._get_transaction_state_from_response(response_code)
        
        # Convertir el monto desde centavos a la unidad correcta
        # El POS OCA recibe el monto multiplicado por 100, por lo que debemos dividirlo
        amount_from_pos = pos_data.get('Amount', 0.0)
        if isinstance(amount_from_pos, str):
            try:
                amount_from_pos = float(amount_from_pos)
            except (ValueError, TypeError):
                amount_from_pos = 0.0
        
        # Convertir desde centavos a la unidad correcta
        corrected_amount = amount_from_pos / 100.0 if amount_from_pos > 0 else 0.0
        
        # Log para debuggear el problema del monto
        _logger.info('OCA Transaction Amount Debug - Original: %s, Corrected: %s', 
                    amount_from_pos, corrected_amount)
        
        # Obtener el número de factura del pedido POS
        invoice_number = self._get_invoice_number_from_relations(pos_order, pos_payment)
        
        # Crear valores para la transacción
        transaction_vals = {
            'provider_id': self._get_oca_provider_id(),
            'payment_method_id': self._get_oca_payment_method_id(),
            'reference': self._generate_oca_reference(pos_data, oca_response),
            'amount': corrected_amount,
            'currency_id': self._get_currency_id(pos_data),
            'state': state,
            'state_message': oca_response.get('msg', ''),
            'partner_id': self._get_partner_id(pos_order, pos_payment),
            'company_id': self._get_company_id(pos_order, pos_payment),
            
            # Campos específicos de OCA
            'pos_id': pos_data.get('PosID'),
            'card_bin': oca_response.get('CardNumber', '')[:6] if oca_response.get('CardNumber') else '',
            'card_last_four': oca_response.get('CardNumber', '')[-4:] if oca_response.get('CardNumber') else '',
            'issuer_code': oca_response.get('Issuer', {}).get('code', '') if isinstance(oca_response.get('Issuer'), dict) else '',
            'issuer_name': oca_response.get('Issuer', {}).get('name', '') if isinstance(oca_response.get('Issuer'), dict) else '',
            'installments': pos_data.get('Installments', 1),
            'acquirer': oca_response.get('Acquirer', ''),
            'ticket_number': oca_response.get('Ticket', ''),
            'batch_number': oca_response.get('Batch', ''),
            'authorization_code': oca_response.get('AuthorizationCode', ''),
            'merchant_number': oca_response.get('Merchant', ''),
            'invoice_number': invoice_number,
            'oca_transaction_id': oca_response.get('TransactionId', ''),
            'oca_response_code': response_code,
            'oca_response_message': oca_response.get('msg', ''),
            'oca_complete_response': json.dumps(oca_response, indent=2, ensure_ascii=False),
            
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
        Determina el estado de la transacción basado en el código de respuesta OCA
        
        Args:
            response_code (str): Código de respuesta OCA
            
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
    def get_oca_display_message(self, oca_response):
        """
        Obtiene el mensaje legible para el usuario según ResponseCode y posResponseCode
        (Anexos 1 y 2 POSLink v135). Prioriza el código del terminal cuando indica rechazo.
        
        Args:
            oca_response (dict): Respuesta del POS (ResponseCode, PosResponseCode/posResponseCode, msg)
            
        Returns:
            str: Mensaje en español para mostrar al usuario
        """
        if not oca_response:
            return 'Error desconocido'
        # Código del terminal (puede venir como PosResponseCode o posResponseCode)
        pos_code = oca_response.get('PosResponseCode') or oca_response.get('posResponseCode')
        pos_response_code = str(pos_code).strip() if pos_code is not None and pos_code != '' else None
        response_code = str(oca_response.get('ResponseCode', '')).strip()
        
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
        return oca_response.get('msg', '') or 'Aprobado'
    
    def _get_transaction_state_with_pos_response(self, response_code, oca_response):
        """
        Determina el estado considerando ResponseCode y posResponseCode.
        Si el terminal rechazó (posResponseCode no aprobado), estado = error.
        
        Args:
            response_code (str): ResponseCode del PLS
            oca_response (dict): Respuesta completa
            
        Returns:
            str: 'done', 'pending' o 'error'
        """
        pos_code = oca_response.get('PosResponseCode') or oca_response.get('posResponseCode')
        pos_response_code = str(pos_code).strip() if pos_code is not None and pos_code != '' else None
        if response_code == '0' and pos_response_code and pos_response_code not in POS_APPROVED_CODES:
            return 'error'
        return self._get_transaction_state_from_response(response_code)
    
    def _get_oca_provider_id(self, account_payment=None):
        """
        Resuelve el ``payment.provider`` para la ``payment.transaction`` OCA.

        Regla: si la tx viene de un ``account.payment``, usar el provider de su
        línea de método (``payment_method_line_id.payment_provider_id``). Esto
        desambigua cuando hay varios providers con ``code='oca'`` (p.ej. una
        configuración multi-moneda): cada pago queda asignado al provider real
        del diario usado, no al primero por orden.

        Fallback: primer provider con ``code='oca'`` (flujo POS).
        """
        if account_payment:
            try:
                account_payment.ensure_one()
                line = account_payment.payment_method_line_id
                prov_line = line.payment_provider_id if line else False
                if prov_line and prov_line.code == 'oca':
                    return prov_line.id
            except Exception as exc:
                _logger.warning(
                    'OCA: no pude leer provider desde account.payment %s: %s',
                    account_payment, exc,
                )
        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'oca')], limit=1,
        )
        if not provider:
            _logger.error(
                'No se encontró el proveedor de pago OCA. Asegúrese de que esté configurado.'
            )
            return 1
        return provider.id
    
    def _get_oca_payment_method_id(self, account_payment=None):
        """
        Resuelve el ``payment.method`` para la ``payment.transaction`` OCA.

        Regla del backend: si la tx viene de un ``account.payment``, usar el
        método de pago elegido en el pago — concretamente el primer
        ``payment.method`` del ``payment.provider`` asociado a la línea de
        método del pago (``payment_method_line_id.payment_provider_id``).
        Si no hay pago o no hay method en esa cadena, fallback al provider
        OCA global. En última instancia, False.
        """
        # 1. Si hay account.payment, usar el provider de su línea de método.
        if account_payment:
            try:
                account_payment.ensure_one()
                line = account_payment.payment_method_line_id
                prov_line = line.payment_provider_id if line else False
                if prov_line and prov_line.payment_method_ids:
                    preferred = prov_line.payment_method_ids.filtered(
                        lambda m: m.code == prov_line.code
                    )
                    return (preferred[:1] or prov_line.payment_method_ids[:1]).id
            except Exception as exc:
                _logger.warning(
                    'OCA: no pude leer method desde account.payment %s: %s',
                    account_payment, exc,
                )
        # 2. Fallback: provider OCA global (preferir code='oca').
        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'oca')], limit=1,
        )
        if provider and provider.payment_method_ids:
            preferred = provider.payment_method_ids.filtered(
                lambda m: m.code == 'oca'
            )
            return (preferred[:1] or provider.payment_method_ids[:1]).id
        # 3. Compat.
        fallback = self.env['payment.method'].sudo().search(
            [('code', '=', 'oca')], limit=1,
        )
        if fallback:
            return fallback.id
        _logger.error(
            'OCA: no se encontró payment.method para el provider; la '
            'transacción quedará sin payment_method_id.'
        )
        return False
    
    def _generate_oca_reference(self, pos_data, oca_response):
        """
        Genera una referencia única para la transacción OCA
        
        Args:
            pos_data (dict): Datos enviados al POS
            oca_response (dict): Respuesta recibida del POS
            
        Returns:
            str: Referencia única
        """
        transaction_id = oca_response.get('TransactionId', '')
        pos_id = pos_data.get('PosID', '')
        timestamp = pos_data.get('TransactionDateTimeyyyyMMddHHmmssSSS', '')
        
        return f"OCA-{pos_id}-{transaction_id}-{timestamp}"
    
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
    
    def update_oca_transaction(self, oca_response):
        """
        Actualiza una transacción OCA existente con nueva información.
        Usa mensaje parseado según POSLink v135 y considera posResponseCode para estado error.
        
        Args:
            oca_response (dict): Nueva respuesta del POS
        """
        response_code = str(oca_response.get('ResponseCode', '999')).strip()
        new_state = self._get_transaction_state_with_pos_response(response_code, oca_response)
        state_message = self.get_oca_display_message(oca_response)
        update_vals = {
            'state': new_state,
            'state_message': state_message,
            'oca_response_code': response_code,
            'oca_response_message': state_message,
            'oca_complete_response': json.dumps(oca_response, indent=2, ensure_ascii=False),
        }
        
        # Actualizar campos específicos si están disponibles en la respuesta
        if oca_response.get('CardNumber'):
            update_vals.update({
                'card_bin': oca_response['CardNumber'][:6],
                'card_last_four': oca_response['CardNumber'][-4:],
            })
        
        if oca_response.get('Issuer'):
            if isinstance(oca_response['Issuer'], dict):
                update_vals.update({
                    'issuer_code': oca_response['Issuer'].get('code', ''),
                    'issuer_name': oca_response['Issuer'].get('name', ''),
                })
            else:
                update_vals['issuer_code'] = str(oca_response['Issuer'])
                update_vals['issuer_name'] = self._resolve_oca_issuer_display(oca_response)

        if (oca_response.get('EmvApplicationName') or '').strip():
            update_vals['issuer_name'] = self._resolve_oca_issuer_display(oca_response)

        if oca_response.get('Acquirer'):
            update_vals['acquirer'] = oca_response['Acquirer']
        
        if oca_response.get('Ticket'):
            update_vals['ticket_number'] = oca_response['Ticket']
        
        if oca_response.get('Batch'):
            update_vals['batch_number'] = oca_response['Batch']
        
        if oca_response.get('AuthorizationCode'):
            update_vals['authorization_code'] = oca_response['AuthorizationCode']
        
        if oca_response.get('Merchant'):
            update_vals['merchant_number'] = oca_response['Merchant']

        # Cuotas: el payload inicial va con Quotas=0 para que el pinpad pida
        # al cliente cuántas cuotas. POSLink devuelve el valor elegido en la
        # respuesta del Query como ``Quota`` (singular) o ``Quotas`` (plural).
        quotas_raw = oca_response.get('Quota', oca_response.get('Quotas'))
        if quotas_raw not in (None, '', False):
            try:
                quotas_int = int(str(quotas_raw).strip())
                if quotas_int >= 1:
                    update_vals['installments'] = quotas_int
            except (TypeError, ValueError):
                pass

        self.write(update_vals)
    
    @api.model
    def create_oca_transaction_with_complete_data(
        self,
        oca_response,
        pos_order=None,
        pos_payment=None,
        transaction_id=None,
        account_payment_id=False,
    ):
        """
        Crea una nueva transacción OCA con la información completa recibida del POS.

        Cuando ``account_payment_id`` viene seteado (flujo backend contable),
        se usa el método de pago seleccionado en el pago (via
        ``payment_method_line_id.payment_provider_id``) en el
        ``payment_method_id`` de la transacción. Si no, se usa el del provider
        OCA global.
        """
        # Determinar el estado considerando ResponseCode y posResponseCode (rechazo = error)
        response_code = str(oca_response.get('ResponseCode', '999')).strip()
        state = self._get_transaction_state_with_pos_response(response_code, oca_response)
        state_message = self.get_oca_display_message(oca_response)
        
        # Obtener el monto desde la respuesta del POS
        total_amount = oca_response.get('TotalAmount', '0')
        if isinstance(total_amount, str):
            try:
                total_amount = float(total_amount)
            except (ValueError, TypeError):
                total_amount = 0.0
        
        # Convertir desde centavos a la unidad correcta
        corrected_amount = total_amount / 100.0 if total_amount > 0 else 0.0
        
        # Log para debuggear el problema del monto
        _logger.info('OCA Complete Transaction Amount Debug - TotalAmount: %s, Corrected: %s', 
                    total_amount, corrected_amount)
        
        # Obtener el número de factura del pedido POS relacionado
        invoice_number = self._get_invoice_number_from_relations(pos_order, pos_payment)
        
        # Log para debuggear la referencia y número de factura
        _logger.info('OCA Invoice Number Debug - Invoice Number: %s, POS Order: %s, POS Payment: %s',
                    invoice_number, pos_order.name if pos_order else 'None', pos_payment.name if pos_payment else 'None')

        account_pay = (
            self.env['account.payment'].browse(account_payment_id).exists()
            if account_payment_id else False
        )

        # Crear valores para la transacción con información completa.
        # Pasamos account_pay al getter para que, en flujo backend, use el
        # method del pago (via payment_method_line_id.payment_provider_id).
        transaction_vals = {
            'provider_id': self._get_oca_provider_id(account_pay),
            'payment_method_id': self._get_oca_payment_method_id(account_pay),
            'reference': self._generate_oca_reference_from_complete_data(oca_response),
            'amount': corrected_amount,
            'currency_id': self._get_currency_id_from_response(oca_response),
            'state': state,
            'state_message': state_message,
            'partner_id': self._get_partner_id(pos_order, pos_payment),
            'company_id': self._get_company_id(pos_order, pos_payment),
            
            # Campos específicos de OCA con información completa
            'pos_id': oca_response.get('PosID'),
            'card_bin': oca_response.get('CardNumber', '')[:6] if oca_response.get('CardNumber') else '',
            'card_last_four': oca_response.get('CardNumber', '')[-4:] if oca_response.get('CardNumber') else '',
            'issuer_code': str(oca_response.get('Issuer', '')),
            'issuer_name': self._resolve_oca_issuer_display(oca_response),
            # Cuotas elegidas por el cliente en el pinpad: POSLink las devuelve
            # en 'Quota' (singular) en la respuesta del Query; se mantiene
            # 'Quotas' (plural) como fallback por compatibilidad con docs.
            'installments': int(
                str(oca_response.get('Quota') or oca_response.get('Quotas') or 1).strip() or 1
            ),
            'acquirer': str(oca_response.get('Acquirer', '')),
            'ticket_number': oca_response.get('Ticket', ''),
            'batch_number': oca_response.get('Batch', ''),
            'authorization_code': oca_response.get('AuthorizationCode', ''),
            'merchant_number': oca_response.get('Merchant', ''),
            'invoice_number': invoice_number,
            'oca_transaction_id': transaction_id or oca_response.get('TransactionId', ''),
            'oca_response_code': response_code,
            'oca_response_message': state_message,
            'oca_complete_response': json.dumps(oca_response, indent=2, ensure_ascii=False),
            
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
    
    def _generate_oca_reference_from_complete_data(self, oca_response):
        """
        Genera una referencia única para la transacción OCA con información completa.

        Se usa al persistir respuestas del pinpad (incl. errores o reversas) cuando
        aún no hay ticket/lote en el dict. Sin TransactionId, todas las filas quedarían
        con reference='OCA' y violan payment_transaction_reference_uniq.

        Args:
            oca_response (dict): Respuesta completa del POS (o dict enriquecido en hilo).

        Returns:
            str: Referencia única para payment.transaction.reference
        """
        # --- Extraer identificadores presentes en la respuesta ---
        pos_id = oca_response.get('PosID', '') or ''
        ticket = oca_response.get('Ticket', '') or ''
        batch = oca_response.get('Batch', '') or ''
        authorization = oca_response.get('AuthorizationCode', '') or ''
        transaction_date = oca_response.get('TransactionDate', '') or ''
        transaction_hour = oca_response.get('TransactionHour', '') or ''
        # TransactionId es estable por operación OCA; suele faltar PosID/Ticket en RC12.
        txn_id = oca_response.get('TransactionId') or oca_response.get('STransactionId')
        if txn_id is not None and txn_id != '':
            txn_id = str(txn_id).strip()
        else:
            txn_id = ''

        # --- Armar referencia: siempre incluir txn_id al final si existe ---
        reference_parts = [
            'OCA',
            pos_id,
            ticket,
            batch,
            authorization,
            transaction_date,
            transaction_hour,
            txn_id,
        ]
        reference = '-'.join([str(p) for p in reference_parts if p])

        # --- Fallback si todo opcional vino vacío (evitar solo "OCA") ---
        if not reference or reference == 'OCA':
            if txn_id:
                reference = f'OCA-{txn_id}'
            elif pos_id or ticket or batch:
                reference = f"OCA-{pos_id}-{ticket}-{batch}".strip('-')
            else:
                reference = f'OCA-{uuid.uuid4().hex[:16]}'

        _logger.info('OCA Reference Generated: %s', reference)
        return reference
    
    def _get_currency_id_from_response(self, oca_response):
        """
        Obtiene el ID de la moneda desde la respuesta del POS
        
        Args:
            oca_response (dict): Respuesta del POS
            
        Returns:
            int: ID de la moneda
        """
        currency_code = oca_response.get('Currency', '858')
        
        # Mapear códigos de moneda OCA a monedas de Odoo
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
    
    def _resolve_oca_issuer_display(self, oca_response):
        """
        Texto de marca/emisor para transacciones OCA: prioriza nombre EMV del pinpad.

        Args:
            oca_response (dict): Respuesta ITD/POSLink.

        Returns:
            str: Valor para issuer_name en payment.transaction.
        """
        if not isinstance(oca_response, dict):
            return self._get_issuer_name(oca_response)
        emv_name = (oca_response.get('EmvApplicationName') or '').strip()
        if emv_name:
            return emv_name
        return self._get_issuer_name(oca_response.get('Issuer'))

    def _get_issuer_name(self, issuer_code):
        """
        Obtiene el nombre del emisor basado en el código
        
        Args:
            issuer_code (int/str): Código del emisor
            
        Returns:
            str: Nombre del emisor
        """
        # Mapeo de códigos OCA / ITD a métodos de pago estándar de Odoo
        issuer_mapping = {
            21: 'OCA',
            5: 'Visa',
            6: 'Mastercard',
            7: 'American Express',
            24: 'Visa',
            52: 'Mastercard',
        }
        
        # Intentar obtener el nombre del método de pago correspondiente
        mapped_name = issuer_mapping.get(int(issuer_code))
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
                           transaction.pos_payment_id.name, transaction.oca_transaction_id)

    # --- Campo nuevo: enlace al pago contable (flujo backend OCA) ---
    account_payment_id = fields.Many2one(
        comodel_name='account.payment',
        string='Pago contable (OCA)',
        index=True,
        copy=False,
        ondelete='set null',
        help='Registro de pago estándar (account.payment) cuando el cobro OCA '
        'se inició desde contabilidad.',
    )

    @api.model
    def oca_run_purchase_query_loop(
        self,
        payment_method,
        query_data,
        base_url_endpoint,
        transaction_id,
        pos_session_id,
        original_purchase_data=None,
    ):
        """
        Consulta processFinancialPurchaseQuery en bucle hasta respuesta final.
        ``payment_method`` es el driver ITD (pos.payment.method o payment.provider).
        """
        import pprint
        from time import sleep
        from .oca_utils import (
            _oca_build_confirm_financial_purchase_payload,
            _oca_card_data_ready_for_confirm,
            _oca_http_post_confirm_financial_purchase,
        )

        payment_method.ensure_one()
        result = {}
        confirm_after_card_read_done = False
        max_iterations = 900
        iteration = 0
        while True:
            iteration += 1
            if iteration > max_iterations:
                _logger.error(
                    'OCA query loop: límite (%s) alcanzado (tx=%s)',
                    max_iterations, transaction_id,
                )
                result = {
                    'ResponseCode': '999',
                    'msg': _('Tiempo máximo de espera en consultas OCA agotado.'),
                    'TransactionId': transaction_id,
                }
                break
            sleep(4)
            query_data['TransactionDateTimeyyyyMMddHHmmssSSS'] = (
                payment_method.get_formatted_timestamp()
            )
            try:
                result = payment_method.processFinancialPurchaseQuery(query_data, base_url_endpoint)
                # DEBUG: cada iteración del loop con su response.
                import pprint as _pp_iter
                _logger.info(
                    '[CUOTAS DEBUG] Query iter %s response (tx=%s):\n%s',
                    iteration, transaction_id, _pp_iter.pformat(result),
                )
                response_code = str(result.get('ResponseCode', '999')).strip()
                # OJO: no usar ``rt_raw not in (False, None, '')`` — en Python
                # ``0.0 == False`` es True, así que con un valor válido de 0.0
                # (pinpad expirado) ese chequeo salta la conversión y ``rt_num``
                # queda None; el bloque de timeout no dispara y el loop queda
                # girando infinitamente. Usamos comparación por identidad + tipo.
                rt_raw = result.get('RemainingExpirationTime')
                rt_num = None
                if isinstance(rt_raw, (int, float)):
                    rt_num = float(rt_raw)
                elif isinstance(rt_raw, str) and rt_raw.strip() != '':
                    try:
                        rt_num = float(rt_raw)
                    except (TypeError, ValueError):
                        rt_num = None

                need_read_card = bool(
                    original_purchase_data
                    and original_purchase_data.get('NeedToReadCard')
                )
                if (
                    need_read_card
                    and not confirm_after_card_read_done
                    and response_code == '12'
                    and _oca_card_data_ready_for_confirm(result)
                ):
                    confirm_payload = _oca_build_confirm_financial_purchase_payload(
                        original_purchase_data, result, transaction_id, payment_method,
                    )
                    try:
                        conf = _oca_http_post_confirm_financial_purchase(
                            base_url_endpoint, confirm_payload,
                        )
                        confirm_after_card_read_done = True
                        crc = str(conf.get('ResponseCode', '999')).strip()
                        if crc in ('999', '-100'):
                            result = conf
                            break
                    except Exception as conf_err:
                        _logger.exception('OCA: fallo processConfirmFinancialPurchase: %s', conf_err)
                        result = {
                            'ResponseCode': '999',
                            'msg': str(conf_err),
                            'TransactionId': transaction_id,
                        }
                        break

                if response_code not in ['10', '12']:
                    break

                if response_code in ['10', '12'] and rt_num is not None and rt_num <= 0:
                    _logger.warning('Tiempo de transacción expirado para %s. Reversión...', transaction_id)
                    reverse_result = payment_method.processFinancialReverse(query_data, base_url_endpoint)
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
                _logger.error('Error en bucle de consulta OCA: %s', str(e))
                result = {
                    'ResponseCode': '999',
                    'msg': 'Error no determinado.',
                    'TransactionId': transaction_id,
                    'error': str(e),
                }
                break
        return result

    @api.model
    def oca_persist_after_query_generic(
        self,
        transaction_id,
        final_result,
        pos_session_id,
        account_payment_id=None,
    ):
        """
        Persiste el resultado del bucle Query cuando el driver es payment.provider
        (flujo contable sin pos.payment.method).
        """
        try:
            tid_key = str(transaction_id).strip()
            transaction = self.sudo().search(
                [('oca_transaction_id', '=', tid_key)], limit=1,
            )
            if transaction:
                transaction.update_oca_transaction(final_result)
                _logger.info('OCA: tx actualizada tras Query (id=%s, driver=provider)', tid_key)
                return
            if account_payment_id:
                self.sudo().create_oca_transaction_with_complete_data(
                    oca_response=final_result,
                    pos_order=None,
                    pos_payment=None,
                    transaction_id=tid_key,
                    account_payment_id=account_payment_id,
                )
                new_tx = self.sudo().search(
                    [('oca_transaction_id', '=', tid_key)], limit=1,
                )
                if new_tx:
                    new_tx.write({
                        'account_payment_id': account_payment_id,
                        'transaction_origin': 'account_payment',
                    })
                _logger.info('OCA: tx creada (account.payment, id=%s)', tid_key)
                return
            pm_model = self.env.get('pos.payment.method')
            if pm_model is not None:
                pm = pm_model.search([('use_payment_terminal', '=', 'oca')], limit=1)
                if pm and hasattr(pm, '_oca_persist_transaction_after_query'):
                    pm._oca_persist_transaction_after_query(
                        transaction_id, final_result, pos_session_id,
                        account_payment_id=account_payment_id,
                    )
                    return
            _logger.error('OCA: no se pudo persistir Query (sin tx/account.payment/PM OCA)')
        except Exception as err:
            _logger.error('OCA oca_persist_after_query_generic: %s', str(err))