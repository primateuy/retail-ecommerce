# -*- coding: utf-8 -*-
"""
Modelo para extender pos.payment con campos específicos de Fiserv ITD
"""

from odoo import fields, models, api
import logging

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    """
    Extensión del modelo pos.payment para incluir campos específicos de Fiserv ITD
    """
    _inherit = 'pos.payment'

    # Campo para el número de factura que se enviará al POS
    invoice_number = fields.Char(
        string='Número de Factura',
        help='Número de factura que se enviará al POS (Invoice Number)'
    )

    # Campo para indicar si es una promoción
    is_promotion = fields.Boolean(
        string='Es Promoción',
        help='Indica si el pago es una promoción'
    )
    
    # Campo para el número de cuotas
    installments = fields.Integer(
        string='Número de Cuotas',
        default=1,
        help='Número de cuotas para el pago'
    )
    
    # Campo para relacionar con la transacción de pago Fiserv
    payment_transaction_id = fields.Many2one(
        'payment.transaction',
        string='Transacción de Pago',
        help='Transacción de pago Fiserv asociada a este pago POS',
        readonly=True,
        copy=False
    )
    
    # Campo para relacionar con la sesión POS (solo lectura, visible si viene de sesión POS)
    pos_session_id = fields.Many2one(
        'pos.session',
        string='Sesión POS',
        help='Sesión del punto de venta donde se realizó el pago',
        readonly=True,
        copy=False,
        compute='_compute_pos_session_id',
        store=False
    )
    
    @api.depends('pos_order_id')
    def _compute_pos_session_id(self):
        """
        Calcula la sesión POS basada en el pedido POS asociado
        
        Este método calcula automáticamente la sesión POS a partir del pedido
        asociado al pago, permitiendo la navegación desde el pago a la sesión.
        """
        for payment in self:
            if payment.pos_order_id and payment.pos_order_id.session_id:
                payment.pos_session_id = payment.pos_order_id.session_id
            else:
                payment.pos_session_id = False
    
    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para generar automáticamente el número de factura
        si no se proporciona uno y asociar transacciones Fiserv
        """
        if not vals.get('invoice_number') and vals.get('pos_order_id'):
            # Generar número de factura basado en el pedido POS
            pos_order = self.env['pos.order'].browse(vals['pos_order_id'])
            if pos_order.exists():
                vals['invoice_number'] = pos_order.name
        
        # Crear el pago primero
        payment = super(PosPayment, self).create(vals)
        
        # Si es un pago Fiserv, intentar asociar transacciones
        if payment.payment_method_id.use_payment_terminal == 'fiserv':
            payment._associate_fiserv_transaction()
        
        return payment
    
    def get_fiserv_invoice_number(self):
        """
        Obtiene el número de factura para enviar al POS Fiserv
        
        Returns:
            str: Número de factura formateado para Fiserv
        """
        self.ensure_one()
        
        if self.invoice_number:
            # Si hay un número de factura específico, usarlo
            return str(self.invoice_number)
        elif self.pos_order_id:
            # Usar el número del pedido POS
            return str(self.pos_order_id.name)
        else:
            # Fallback: usar el ID del pago
            return str(self.id)
    
    def prepare_fiserv_data(self):
        """
        Prepara los datos para enviar al POS Fiserv
        
        Returns:
            dict: Datos formateados para Fiserv
        """
        self.ensure_one()
        
        # Obtener el método de pago Fiserv
        payment_method = self.payment_method_id
        
        if not payment_method or payment_method.use_payment_terminal != 'fiserv':
            return {}
        
        # Preparar datos básicos
        branch = payment_method.fiserv_branch or ''
        if not branch and payment_method.codigo_sucursal is not None:
            branch = str(payment_method.codigo_sucursal)
        fiserv_data = {
            'PosID': payment_method.codigo_terminal,
            'SystemId': payment_method.codigo_sistema,
            'Branch': branch,
            'ClientAppId': payment_method.client_app_id,
            'UserId': self.env.user.id,
            'Amount': self.amount,
            'Currency': self.currency_id.name,
            'Installments': self.installments,
            'InvoiceNumber': self.get_fiserv_invoice_number(),
            'TransactionDateTimeyyyyMMddHHmmssSSS': payment_method.get_formatted_timestamp(),
        }
        
        return fiserv_data
    
    def _associate_fiserv_transaction(self):
        """
        Asocia transacciones Fiserv huérfanas con este pago
        
        Este método se ejecuta cuando se crea un pago Fiserv para buscar y asociar
        transacciones Fiserv que no tengan pago asociado
        """
        try:
            # Obtener los valores de forma segura para evitar errores de cursor
            payment_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            payment_amount = getattr(self, 'amount', 0.0)
            
            _logger.info('Buscando transacciones Fiserv para asociar con pago: %s (Monto: %s)', 
                        payment_name, payment_amount)
            
            fiserv_provider = self.env['payment.provider'].sudo().search(
                [('code', '=', 'fiserv')], limit=1
            )
            domain = [
                ('fiserv_transaction_id', '!=', False),
                ('pos_payment_id', '=', False),
                ('state', 'in', ['pending', 'done']),
            ]
            if fiserv_provider:
                domain.append(('provider_id', '=', fiserv_provider.id))
            orphaned_transactions = self.env['payment.transaction'].sudo().search(domain)
            
            if not orphaned_transactions:
                _logger.info('No se encontraron transacciones Fiserv huérfanas para asociar')
                return
            
            _logger.info('Encontradas %s transacciones Fiserv huérfanas para evaluar', len(orphaned_transactions))
            
            # Buscar transacción que coincida por monto
            matching_transaction = None
            best_score = 0
            
            for transaction in orphaned_transactions:
                # Calcular score de coincidencia
                score = 0
                
                # Coincidencia exacta de monto (score alto)
                if abs(transaction.amount - payment_amount) < 0.01:
                    score += 100
                    _logger.info('Coincidencia exacta de monto: Transacción %s (%.2f) = Pago %s (%.2f)', 
                               transaction.fiserv_transaction_id, transaction.amount, 
                               payment_name, payment_amount)
                # Coincidencia aproximada de monto (score medio)
                elif abs(transaction.amount - payment_amount) < 1.0:
                    score += 50
                    _logger.info('Coincidencia aproximada de monto: Transacción %s (%.2f) ≈ Pago %s (%.2f)', 
                               transaction.fiserv_transaction_id, transaction.amount, 
                               payment_name, payment_amount)
                
                # Verificar que la transacción no esté ya asociada a otro pago
                if transaction.pos_payment_id:
                    existing_payment_name = getattr(transaction.pos_payment_id, 'name', 'Unknown') or 'Unknown'
                    _logger.info('Transacción %s ya asociada a pago %s, saltando...', 
                               transaction.fiserv_transaction_id, existing_payment_name)
                    continue
                
                # Si es la mejor coincidencia hasta ahora, guardarla
                if score > best_score:
                    best_score = score
                    matching_transaction = transaction
                    _logger.info('Nueva mejor coincidencia: Transacción %s (Score: %s)', 
                               transaction.fiserv_transaction_id, score)
            
            if matching_transaction and best_score > 0:
                # Asociar la transacción con este pago
                matching_transaction.pos_payment_id = self.id
                
                # Actualizar el campo payment_transaction_id en este pago
                self.payment_transaction_id = matching_transaction.id
                
                # Si la transacción no tiene orden asociada y este pago tiene orden, asociarla
                if not matching_transaction.pos_order_id and self.pos_order_id:
                    matching_transaction.pos_order_id = self.pos_order_id.id
                    
                    # Actualizar el número de factura
                    order_name = getattr(self.pos_order_id, 'name', None)
                    if order_name:
                        matching_transaction.invoice_number = order_name
                
                order_name = getattr(self.pos_order_id, 'name', 'None') if self.pos_order_id else 'None'
                _logger.info('Transacción Fiserv asociada exitosamente: %s -> Pago: %s, Orden: %s (Score: %s)', 
                           matching_transaction.fiserv_transaction_id, payment_name, order_name, best_score)
            else:
                _logger.warning('No se encontró transacción Fiserv para el pago: %s (Monto: %s)', 
                              payment_name, payment_amount)
            
        except Exception as e:
            _logger.error('Error al asociar transacción Fiserv con pago ID %s: %s', self.id, str(e)) 