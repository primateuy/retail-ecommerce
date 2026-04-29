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
        ('account_payment', 'Pago contable'),
        ('other', 'Otro'),
    ], string='Origen de Transacción', default='pos_payment')
    
    account_payment_id = fields.Many2one(
        comodel_name='account.payment',
        string='Pago contable',
        ondelete='set null',
        help='Registro de pago estándar (account.payment) cuando el cobro ITD se inició desde contabilidad.',
    )
    
    # Los Many2one a 'pos.order' y 'pos.payment' viven en odoo_pos_fiserv_pos
    # (modelo extendido por _inherit). Si solo está instalado el backend,
    # esos campos no existen en payment.transaction y la lectura del registro
    # no falla con _unknown.

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
        Sincroniza ``account.payment.payment_transaction_id`` cuando cambia el
        ``account_payment_id`` de la transacción. La sincronización con
        ``pos.payment`` vive en ``odoo_pos_fiserv_pos`` para no acoplar el core
        al módulo POS.
        """
        if 'account_payment_id' in vals:
            new_ap_id = vals.get('account_payment_id')
            old_ap_id = self.account_payment_id.id if self.account_payment_id else False
            if old_ap_id and old_ap_id != new_ap_id:
                old_ap = self.env['account.payment'].browse(old_ap_id)
                if old_ap.exists() and old_ap.payment_transaction_id.id == self.id:
                    old_ap.payment_transaction_id = False
            if new_ap_id:
                new_ap = self.env['account.payment'].browse(new_ap_id)
                if new_ap.exists():
                    new_ap.payment_transaction_id = self.id
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
        # Transacción ya vinculada a un pago contable existente: no duplicar account.payment
        if self.transaction_origin == 'account_payment' and self.account_payment_id:
            _logger.info(
                'Fiserv: transacción %s ya asociada a account.payment %s; no se crea pago duplicado.',
                self.reference,
                self.account_payment_id.id,
            )
            return self.account_payment_id

        # Identificar transacciones que provienen del POS Fiserv (no crear account.payment).
        # Sin POS instalado los campos pos_*_id no existen, por eso se chequean por _fields.
        has_pos_payment = (
            'pos_payment_id' in self._fields and bool(self.pos_payment_id)
        )
        is_pos_fiserv = (
            self.transaction_origin in ('pos_payment', 'pos_order')
            or has_pos_payment
        )
        if is_pos_fiserv:
            _logger.info(
                'Fiserv POS: omitiendo creación de account.payment para transacción %s '
                '(reference=%s, transaction_origin=%s). '
                'El cobro ya está registrado en pos.payment.',
                self.fiserv_transaction_id or self.reference,
                self.reference,
                self.transaction_origin,
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

        # Si la operación es void o refund (ITD las identifica por la presencia de
        # ``TicketNumber`` en el payload), el monto se almacena en negativo para
        # que la payment.transaction refleje la dirección del dinero (salida).
        # ITD recibe siempre el monto positivo en el payload; el signo es solo
        # para representación contable interna.
        if (pos_data or {}).get('TicketNumber') and corrected_amount > 0:
            corrected_amount = -corrected_amount

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

            'transaction_origin': 'pos_payment' if pos_payment else 'pos_order' if pos_order else 'other',
        }
        # Campos POS: solo si odoo_pos_fiserv_pos los aportó (no romper sin POS).
        if pos_order and 'pos_order_id' in self._fields:
            transaction_vals['pos_order_id'] = pos_order.id
        if pos_payment and 'pos_payment_id' in self._fields:
            transaction_vals['pos_payment_id'] = pos_payment.id

        # Crear la transacción
        transaction = self.create(transaction_vals)

        # Sincronizar pos_payment.payment_transaction_id solo si el campo existe
        # en pos.payment (lo agrega odoo_pos_fiserv_pos_payment u odoo_pos_oca).
        if pos_payment and 'payment_transaction_id' in pos_payment._fields:
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
    
    def _get_fiserv_provider_id(self, account_payment=None):
        """
        Resuelve el ``payment.provider`` para la ``payment.transaction`` Fiserv.

        Regla: si la tx viene de un ``account.payment``, usar el provider de su
        línea de método (``payment_method_line_id.payment_provider_id``). Esto
        desambigua cuando hay varios providers con ``code='fiserv'`` (p.ej.
        "Fiserv ITD" UYU y "Fiserv ITD USD"): cada pago queda asignado al
        provider real del diario usado, no al primero por orden.

        Fallback: primer provider con ``code='fiserv'`` (flujo POS).
        """
        if account_payment:
            try:
                account_payment.ensure_one()
                line = account_payment.payment_method_line_id
                prov_line = line.payment_provider_id if line else False
                if prov_line and prov_line.code == 'fiserv':
                    return prov_line.id
            except Exception as exc:
                _logger.warning(
                    'Fiserv: no pude leer provider desde account.payment %s: %s',
                    account_payment, exc,
                )
        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'fiserv')], limit=1,
        )
        if not provider:
            _logger.error(
                'No se encontró el proveedor de pago Fiserv. '
                'Configúrelo en Contabilidad / Pagos en línea.'
            )
            return 1
        return provider.id
    
    def _get_fiserv_payment_method_id(self, account_payment=None):
        """
        Resuelve el ``payment.method`` (módulo ``payment``) para la
        ``payment.transaction`` Fiserv.

        Regla del backend: si la tx viene de un ``account.payment``, usar el
        método de pago elegido en el pago — concretamente el primer
        ``payment.method`` del ``payment.provider`` asociado a la línea de
        método del pago (``payment_method_line_id.payment_provider_id``).
        Si no hay pago o no hay method en esa cadena, fallback al primer
        method del provider Fiserv global. En última instancia, False.
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
                    'Fiserv: no pude leer method desde account.payment %s: %s',
                    account_payment, exc,
                )
        # 2. Fallback: provider Fiserv global (preferir code='fiserv').
        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'fiserv')], limit=1,
        )
        if provider and provider.payment_method_ids:
            preferred = provider.payment_method_ids.filtered(
                lambda m: m.code == 'fiserv'
            )
            return (preferred[:1] or provider.payment_method_ids[:1]).id
        # 3. Compat: payment.method con code='fiserv'.
        fallback = self.env['payment.method'].sudo().search(
            [('code', '=', 'fiserv')], limit=1,
        )
        if fallback:
            return fallback.id
        _logger.error(
            'Fiserv: no se encontró payment.method para el provider; la '
            'transacción quedará sin payment_method_id.'
        )
        return False
    
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
    
    def _fiserv_corrected_amount_from_total_amount(self, itd_response):
        """
        Convierte TotalAmount ITD (centavos) a importe de transacción Odoo.

        Misma regla que en ``create_fiserv_transaction_with_complete_data``: si no hay
        monto válido, devuelve None y el llamador no pisa ``amount`` en el write.

        Args:
            itd_response (dict): Respuesta ITD.

        Returns:
            float|None: Importe en unidad de moneda, o None si no aplica actualizar.
        """
        if 'TotalAmount' not in itd_response:
            return None
        total_amount = itd_response.get('TotalAmount', '0')
        if isinstance(total_amount, str):
            try:
                total_amount = float(total_amount)
            except (ValueError, TypeError):
                return None
        else:
            try:
                total_amount = float(total_amount)
            except (TypeError, ValueError):
                return None
        if total_amount <= 0:
            return None
        return total_amount / 100.0

    def _fiserv_is_outbound_tx(self):
        """
        Indica si esta payment.transaction representa una anulación o devolución
        (salida de dinero), para guardar ``amount`` con signo negativo.

        Discriminadores por orden de prioridad:
        1) ``self.amount < 0``: la creación inicial ya marcó signo (vía pos_data
           con TicketNumber o vía relación outbound). Preservar.
        2) ``account_payment_id.payment_type == 'outbound'``: devolución por
           ticket desde contabilidad.
        3) ``pos_payment_id.amount < 0`` (si el módulo POS lo aporta): refund
           registrado como pago POS.
        4) ``pos_order_id.amount_total < 0`` (si el módulo POS lo aporta):
           pedido de devolución POS.

        Returns:
            bool: True si la tx debe almacenar ``amount`` en negativo.
        """
        self.ensure_one()
        if self.amount and self.amount < 0:
            return True
        ap = self.account_payment_id if 'account_payment_id' in self._fields else False
        if ap and ap.payment_type == 'outbound':
            return True
        if 'pos_payment_id' in self._fields:
            pp = self.pos_payment_id
            if pp and getattr(pp, 'amount', 0) < 0:
                return True
        if 'pos_order_id' in self._fields:
            po = self.pos_order_id
            if po and getattr(po, 'amount_total', 0) < 0:
                return True
        return False

    def update_fiserv_transaction(self, itd_response):
        """
        Actualiza una transacción Fiserv existente con nueva información.
        Usa mensaje parseado según POSLink v135 y considera posResponseCode para estado error.

        Tras un error temprano en el bucle Query (p. ej. excepción antes del éxito), la
        transacción puede haberse creado con referencia genérica «FISERV», importe 0 y sin
        datos de ticket; cuando llega la respuesta final aprobada, aquí se deben alinear
        referencia, importe, PosID y demás campos igual que en la creación «completa».

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

        # --- Referencia legible: al actualizar tras Query, debe coincidir con creación completa ---
        update_vals['reference'] = self._generate_fiserv_reference_from_complete_data(itd_response)

        # --- Importe desde TotalAmount cuando ITD lo envía (p. ej. respuesta final RC=0) ---
        corrected_amount = self._fiserv_corrected_amount_from_total_amount(itd_response)
        if corrected_amount is not None:
            # Preservar signo negativo en void/refund: ITD siempre devuelve
            # ``TotalAmount`` positivo, pero la payment.transaction guardada en
            # negativo debe seguir reflejando salida de dinero. Si la tx ya estaba
            # con monto negativo (creada por el path void/refund), o si la relación
            # contable/POS indica devolución, forzamos signo negativo.
            if corrected_amount > 0 and self._fiserv_is_outbound_tx():
                corrected_amount = -corrected_amount
            update_vals['amount'] = corrected_amount

        # --- PosID y moneda si vienen en la respuesta ---
        if itd_response.get('PosID'):
            update_vals['pos_id'] = itd_response['PosID']
        if itd_response.get('Currency'):
            update_vals['currency_id'] = self._get_currency_id_from_response(itd_response)

        # --- Cuotas (Quota en ITD) ---
        if itd_response.get('Quota') is not None and itd_response.get('Quota') != '':
            update_vals['installments'] = self._parse_itd_quota(itd_response.get('Quota', 0))

        # Actualizar campos específicos si están disponibles en la respuesta
        if itd_response.get('CardNumber'):
            card_num = str(itd_response['CardNumber'])
            if len(card_num) >= 10:
                update_vals.update({
                    'card_bin': card_num[:6],
                    'card_last_four': card_num[-4:],
                })
            elif len(card_num) >= 6:
                update_vals.update({
                    'card_bin': card_num[:6],
                    'card_last_four': '',
                })

        if itd_response.get('Issuer'):
            if isinstance(itd_response['Issuer'], dict):
                update_vals.update({
                    'issuer_code': itd_response['Issuer'].get('code', ''),
                    'issuer_name': itd_response['Issuer'].get('name', ''),
                })
            else:
                # --- Código numérico ITD: enriquecer con EMV o tabla Fiserv ---
                update_vals['issuer_code'] = str(itd_response['Issuer'])
                update_vals['issuer_name'] = self._get_fiserv_card_brand_display_name(itd_response)

        # --- Nombre de aplicación EMV (chip) prevalece sobre issuer genérico ---
        if (itd_response.get('EmvApplicationName') or '').strip():
            update_vals['issuer_name'] = self._get_fiserv_card_brand_display_name(itd_response)

        if itd_response.get('Acquirer') is not None and itd_response.get('Acquirer') != '':
            update_vals['acquirer'] = str(itd_response['Acquirer'])

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
    def create_fiserv_transaction_with_complete_data(
        self,
        itd_response,
        pos_order=None,
        pos_payment=None,
        transaction_id=None,
        account_payment_id=False,
    ):
        """
        Crea una nueva transacción Fiserv con la información completa recibida del POS
        
        Args:
            itd_response (dict): Respuesta completa del POS
            pos_order (pos.order): Pedido POS relacionado
            pos_payment (pos.payment): Pago POS relacionado
            transaction_id (str): ID de la transacción Fiserv
            account_payment_id (int|bool): ID de account.payment si el cobro fue desde contabilidad.
            
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
        
        # --- Número de referencia para ITD / UI: pedido POS, pago contable o texto por defecto ---
        account_pay = (
            self.env['account.payment'].browse(account_payment_id)
            if account_payment_id
            else self.env['account.payment']
        )
        if account_pay:
            invoice_number = account_pay.ref or account_pay.name or 'Pago-%s' % account_pay.id
        else:
            invoice_number = self._get_invoice_number_from_relations(pos_order, pos_payment)
        
        # Log para debuggear la referencia y número de factura
        _logger.info(
            'Fiserv Invoice Number Debug - Invoice Number: %s, POS Order: %s, POS Payment: %s, account.payment: %s',
            invoice_number,
            pos_order.name if pos_order else 'None',
            pos_payment.name if pos_payment else 'None',
            account_pay.id if account_pay else None,
        )
        
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

        # --- Partner y compañía: prioridad pago contable sobre relaciones POS ---
        if account_pay:
            partner_id = account_pay.partner_id.id
            company_id = account_pay.company_id.id
        else:
            partner_id = self._get_partner_id(pos_order, pos_payment)
            company_id = self._get_company_id(pos_order, pos_payment)

        # Void/refund → monto en negativo en la payment.transaction (representación
        # contable de salida de dinero). Discriminadores por orden de prioridad:
        # 1) pago contable outbound (devolución por ticket desde backend),
        # 2) pos.payment con amount negativo (refund POS),
        # 3) pos.order con amount_total negativo (orden de devolución POS).
        if corrected_amount > 0:
            is_outbound_op = False
            if account_pay and account_pay.payment_type == 'outbound':
                is_outbound_op = True
            elif pos_payment and getattr(pos_payment, 'amount', 0) < 0:
                is_outbound_op = True
            elif pos_order and getattr(pos_order, 'amount_total', 0) < 0:
                is_outbound_op = True
            if is_outbound_op:
                corrected_amount = -corrected_amount

        tx_origin = 'account_payment' if account_pay else (
            'pos_payment' if pos_payment else 'pos_order' if pos_order else 'other'
        )

        # Crear valores para la transacción con información completa.
        # Pasamos account_pay al getter del method para que, si la tx viene
        # del backend, use el provider/method de la línea de pago del usuario.
        transaction_vals = {
            'provider_id': self._get_fiserv_provider_id(account_pay),
            'payment_method_id': self._get_fiserv_payment_method_id(account_pay),
            'reference': self._generate_fiserv_reference_from_complete_data(itd_response),
            'amount': corrected_amount,
            'currency_id': self._get_currency_id_from_response(itd_response),
            'state': state,
            'state_message': state_message,
            'partner_id': partner_id,
            'company_id': company_id,
            
            # Campos específicos de Fiserv ITD con información completa
            'pos_id': itd_response.get('PosID'),
            'card_bin': itd_response.get('CardNumber', '')[:6] if itd_response.get('CardNumber') else '',
            'card_last_four': itd_response.get('CardNumber', '')[-4:] if itd_response.get('CardNumber') else '',
            'issuer_code': str(itd_response.get('Issuer', '')),
            'issuer_name': self._get_fiserv_card_brand_display_name(itd_response),
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

            'account_payment_id': account_pay.id if account_pay else False,
            'transaction_origin': tx_origin,
        }
        # Campos POS: solo si odoo_pos_fiserv_pos los aportó (no romper sin POS).
        if pos_order and 'pos_order_id' in self._fields:
            transaction_vals['pos_order_id'] = pos_order.id
        if pos_payment and 'pos_payment_id' in self._fields:
            transaction_vals['pos_payment_id'] = pos_payment.id

        # Crear la transacción
        transaction = self.create(transaction_vals)

        # Sincronizar pos_payment.payment_transaction_id solo si el campo existe.
        if pos_payment and 'payment_transaction_id' in pos_payment._fields:
            pos_payment.payment_transaction_id = transaction.id

        if account_pay:
            account_pay.payment_transaction_id = transaction.id

        return transaction
    
    def _generate_fiserv_reference_from_complete_data(self, itd_response):
        """
        Genera una referencia única para la transacción Fiserv con información completa
        
        Args:
            itd_response (dict): Respuesta completa del POS
            
        Returns:
            str: Referencia única
        """
        pos_id = str(itd_response.get('PosID', '') or '').strip()
        ticket = str(itd_response.get('Ticket', '') or '').strip()
        batch = str(itd_response.get('Batch', '') or '').strip()
        authorization = str(itd_response.get('AuthorizationCode', '') or '').strip()
        transaction_date = str(itd_response.get('TransactionDate', '') or '').strip()
        transaction_hour = str(itd_response.get('TransactionHour', '') or '').strip()

        # Crear una referencia más completa y única
        reference_parts = [
            'FISERV',
            pos_id,
            ticket,
            batch,
            authorization,
            transaction_date,
            transaction_hour,
        ]

        # Filtrar partes vacías y unir
        reference = '-'.join([part for part in reference_parts if part])

        # Si la referencia está vacía, usar un fallback con PosID/ticket/lote
        if not reference:
            reference = '-'.join(
                p for p in ('FISERV', pos_id, ticket, batch) if p
            )

        # --- Sin ticket ni datos aún: evitar solo «FISERV» (ambiguo en listas y búsquedas) ---
        tid = str(itd_response.get('TransactionId', '') or '').strip()
        if tid and reference in ('FISERV', ''):
            reference = f'FISERV-{tid}'

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
    
    def _get_fiserv_card_brand_display_name(self, itd_response):
        """
        Nombre de marca para mostrar: prioriza EMV (p. ej. Mastercard) sobre el código Issuer.

        ITD suele enviar EmvApplicationName cuando la tarjeta pasó chip; el código Issuer
        a veces no coincide con tablas locales y generaba textos genéricos tipo «Emisor 52».

        Args:
            itd_response (dict): Respuesta completa del pinpad / ITD.

        Returns:
            str: Texto legible para issuer_name en payment.transaction.
        """
        if not isinstance(itd_response, dict):
            return self._get_fiserv_issuer_name(itd_response)
        emv_name = (itd_response.get('EmvApplicationName') or '').strip()
        if emv_name:
            return emv_name
        return self._get_fiserv_issuer_name(itd_response.get('Issuer'))

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
    
    # update_payment_transaction_reference vive en odoo_pos_fiserv_pos:
    # depende de pos_payment_id (modelo pos.payment) y solo tiene sentido si el
    # POS está instalado.

    @api.model
    def fiserv_run_purchase_query_loop(
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

        Si el cobro inicial llevó NeedToReadCard=True (TPV y account.payment), ITD pasa por
        RC 10/12 hasta leer la tarjeta y exige un único POST processConfirmFinancialPurchase
        para enviar al host; sin eso el pinpad queda en «Enviando al host» y Query devuelve 12
        en bucle.

        ``payment_method`` es el driver ITD (puede ser ``pos.payment.method`` o
        ``payment.provider``); ambos exponen ``get_formatted_timestamp``,
        ``processFinancialPurchaseQuery`` y ``processFinancialReverse``.
        """
        import pprint
        from time import sleep
        from odoo import _
        from .fiserv_utils import (
            _fiserv_build_confirm_financial_purchase_payload,
            _fiserv_card_data_ready_for_confirm,
            _fiserv_http_post_confirm_financial_purchase,
        )

        payment_method.ensure_one()
        result = {}
        # Tras RC=12 solo se confirma una vez; ITD continúa el flujo hacia aprobación o error
        confirm_after_card_read_done = False
        max_iterations = 900
        iteration = 0
        while True:
            iteration += 1
            if iteration > max_iterations:
                _logger.error(
                    'Fiserv query loop: límite de iteraciones (%s) alcanzado (tx=%s)',
                    max_iterations,
                    transaction_id,
                )
                result = {
                    'ResponseCode': '999',
                    'msg': _(
                        'Tiempo máximo de espera en consultas ITD agotado. '
                        'Revise el pinpad o reintente.'
                    ),
                    'TransactionId': transaction_id,
                }
                break
            sleep(4)
            query_data['TransactionDateTimeyyyyMMddHHmmssSSS'] = (
                payment_method.get_formatted_timestamp()
            )
            _logger.info('>>>Intento Fiserv query>>>')
            try:
                result = payment_method.processFinancialPurchaseQuery(query_data, base_url_endpoint)
                _logger.info('Result: %s', pprint.pformat(result))

                response_code = str(result.get('ResponseCode', '999')).strip()
                rt_raw = result.get('RemainingExpirationTime', False)
                rt_num = None
                if rt_raw is not False and rt_raw is not None and rt_raw != '':
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
                    and _fiserv_card_data_ready_for_confirm(result)
                ):
                    confirm_payload = _fiserv_build_confirm_financial_purchase_payload(
                        original_purchase_data,
                        result,
                        transaction_id,
                        payment_method,
                    )
                    _logger.info(
                        'Fiserv ITD: processConfirmFinancialPurchase tras RC=12 | tx=%s',
                        transaction_id,
                    )
                    try:
                        conf = _fiserv_http_post_confirm_financial_purchase(
                            base_url_endpoint,
                            confirm_payload,
                        )
                        confirm_after_card_read_done = True
                        crc = str(conf.get('ResponseCode', '999')).strip()
                        if crc in ('999', '-100'):
                            result = conf
                            break
                    except Exception as conf_err:
                        _logger.exception(
                            'Fiserv: fallo HTTP/JSON en processConfirmFinancialPurchase: %s',
                            conf_err,
                        )
                        result = {
                            'ResponseCode': '999',
                            'msg': str(conf_err),
                            'TransactionId': transaction_id,
                        }
                        break

                if response_code not in ['10', '12']:
                    break

                if response_code in ['10', '12'] and rt_num is not None and rt_num <= 0:
                    _logger.warning(
                        'Tiempo de transacción expirado para %s. Reversión...',
                        transaction_id,
                    )
                    reverse_result = payment_method.processFinancialReverse(
                        query_data, base_url_endpoint
                    )
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
                _logger.error('Error en bucle de consulta Fiserv: %s', str(e))
                result = {
                    'ResponseCode': '999',
                    'msg': 'Error no determinado.',
                    'TransactionId': transaction_id,
                    'error': str(e),
                }
                break
            _logger.info('>>>FIN Intento Fiserv query>>>')

        return result

    @api.model
    def fiserv_persist_after_query_generic(
        self,
        transaction_id,
        final_result,
        pos_session_id,
        account_payment_id=None,
    ):
        """
        Persiste el resultado del bucle Query cuando el driver ITD es ``payment.provider``.

        No depende de ``pos.payment.method``; se usa tanto para cobro contable directo como
        desde POS (con el método POS como fallback si la transacción aún no existe).
        """
        try:
            tid_key = str(transaction_id).strip()
            transaction = self.sudo().search(
                [('fiserv_transaction_id', '=', tid_key)],
                limit=1,
            )
            if transaction:
                transaction.update_fiserv_transaction(final_result)
                _logger.info(
                    'Fiserv: transacción actualizada tras Query (id ITD=%s, driver=provider)',
                    tid_key,
                )
                return
            if account_payment_id:
                self.sudo().create_fiserv_transaction_with_complete_data(
                    itd_response=final_result,
                    pos_order=None,
                    pos_payment=None,
                    transaction_id=tid_key,
                    account_payment_id=account_payment_id or False,
                )
                _logger.info(
                    'Fiserv: transacción creada tras Query (account.payment, id ITD=%s)',
                    tid_key,
                )
                return
            # Fallback flujo POS: si el módulo POS está instalado, persistir por su método.
            pm_model = self.env.get('pos.payment.method')
            if pm_model is not None:
                pm = pm_model.search([('use_payment_terminal', '=', 'fiserv')], limit=1)
                if pm:
                    pm._fiserv_persist_transaction_after_query(
                        transaction_id,
                        final_result,
                        pos_session_id,
                        account_payment_id=account_payment_id,
                    )
                    return
            _logger.error(
                'Fiserv: no se pudo persistir Query (sin tx, sin account.payment, sin PM Fiserv)'
            )
        except Exception as err:
            _logger.error('Fiserv fiserv_persist_after_query_generic: %s', str(err))
