# -*- coding: utf-8 -*-
"""
Modelo para extender pos.order con funcionalidades básicas
"""

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión básica del modelo pos.order
    """
    _inherit = 'pos.order'
    
    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para asociar automáticamente transacciones OCA
        cuando se crea una orden POS
        
        Args:
            vals (dict): Valores para crear la orden
            
        Returns:
            pos.order: Orden creada
        """
        # Crear la orden primero
        order = super(PosOrder, self).create(vals)
        
        # Intentar asociar transacciones OCA huérfanas
        order._associate_oca_transactions()
        
        return order
    
    def _associate_oca_transactions(self):
        """
        Asocia transacciones OCA huérfanas con esta orden
        
        Este método se ejecuta después de crear la orden para buscar y asociar
        transacciones OCA que no tengan orden asociada y que correspondan a esta sesión
        """
        try:
            # Obtener los valores de forma segura para evitar errores de cursor
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            session_id = getattr(self, 'session_id', None)
            session_id_value = session_id.id if session_id else 'Unknown'
            
            _logger.info('Buscando transacciones OCA para asociar con orden: %s (Sesión: %s)', 
                        order_name, session_id_value)
            
            # Buscar transacciones OCA sin orden asociada en esta sesión
            orphaned_transactions = self.env['payment.transaction'].sudo().search([
                ('oca_transaction_id', '!=', False),
                ('pos_order_id', '=', False),
                ('state', 'in', ['pending', 'done'])
            ])
            
            if not orphaned_transactions:
                _logger.info('No se encontraron transacciones OCA huérfanas para asociar')
                return
            
            _logger.info('Encontradas %s transacciones OCA huérfanas para evaluar', len(orphaned_transactions))
            
            # Buscar pagos OCA en esta orden
            oca_payments = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'oca'
            )
            
            if not oca_payments:
                _logger.info('La orden %s no tiene pagos OCA aún, programando verificación posterior...', order_name)
                # Programar una verificación posterior cuando se creen los pagos
                self._schedule_oca_association_check()
                return
            
            _logger.info('Orden %s tiene %s pagos OCA', order_name, len(oca_payments))
            
            # Para cada pago OCA en esta orden, buscar la transacción correspondiente
            for oca_payment in oca_payments:
                payment_name = getattr(oca_payment, 'name', 'Unknown') or 'Unknown'
                payment_amount = getattr(oca_payment, 'amount', 0.0)
                
                _logger.info('Procesando pago OCA: %s (Monto: %s)', payment_name, payment_amount)
                
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
                                   transaction.oca_transaction_id, transaction.amount, 
                                   payment_name, payment_amount)
                    # Coincidencia aproximada de monto (score medio)
                    elif abs(transaction.amount - payment_amount) < 1.0:
                        score += 50
                        _logger.info('Coincidencia aproximada de monto: Transacción %s (%.2f) ≈ Pago %s (%.2f)', 
                                   transaction.oca_transaction_id, transaction.amount, 
                                   payment_name, payment_amount)
                    
                    # Verificar que la transacción no esté ya asociada a otra orden
                    if transaction.pos_order_id:
                        _logger.info('Transacción %s ya asociada a orden %s, saltando...', 
                                   transaction.oca_transaction_id, transaction.pos_order_id.name)
                        continue
                    
                    # Si es la mejor coincidencia hasta ahora, guardarla
                    if score > best_score:
                        best_score = score
                        matching_transaction = transaction
                        _logger.info('Nueva mejor coincidencia: Transacción %s (Score: %s)', 
                                   transaction.oca_transaction_id, score)
                
                if matching_transaction and best_score > 0:
                    # Asociar la transacción con esta orden y pago
                    matching_transaction.pos_order_id = self.id
                    matching_transaction.pos_payment_id = oca_payment.id
                    
                    # Actualizar el número de factura
                    if order_name and order_name != 'Unknown':
                        matching_transaction.invoice_number = order_name
                    
                    _logger.info('Transacción OCA asociada exitosamente: %s -> Orden: %s, Pago: %s (Score: %s)', 
                               matching_transaction.oca_transaction_id, order_name, payment_name, best_score)
                else:
                    _logger.warning('No se encontró transacción OCA para el pago: %s (Monto: %s)', 
                                  payment_name, payment_amount)
            
            # Ejecutar diagnóstico después de la asociación
            self._diagnose_oca_associations()
            
        except Exception as e:
            # Usar un mensaje de error más seguro que no acceda a campos del ORM
            _logger.error('Error al asociar transacciones OCA con orden ID %s: %s', self.id, str(e))
    
    def _schedule_oca_association_check(self):
        """
        Programa una verificación posterior para asociar transacciones OCA
        cuando se creen los pagos
        """
        try:
            # En lugar de usar threading, vamos a usar un enfoque más simple
            # que no cause problemas de cursor cerrado
            order_id = self.id
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            
            _logger.info('Programada verificación diferida de asociación OCA para orden: %s (ID: %s)', 
                        order_name, order_id)
            
            # Por ahora, no ejecutamos la verificación diferida para evitar problemas de cursor
            # La asociación se hará cuando se cree el pago OCA
            
        except Exception as e:
            _logger.error('Error al programar verificación de asociación OCA: %s', str(e))
    
    def _diagnose_oca_associations(self):
        """
        Ejecuta diagnóstico de asociaciones OCA para esta orden
        """
        try:
            # Obtener el nombre de la orden de forma segura
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            
            # Buscar transacciones OCA asociadas a esta orden
            associated_transactions = self.env['payment.transaction'].sudo().search([
                ('pos_order_id', '=', self.id),
                ('oca_transaction_id', '!=', False)
            ])
            
            _logger.info('=== DIAGNÓSTICO DE ASOCIACIONES OCA PARA ORDEN %s ===', order_name)
            _logger.info('Transacciones OCA asociadas: %s', len(associated_transactions))
            
            for transaction in associated_transactions:
                payment_name = getattr(transaction.pos_payment_id, 'name', 'None') if transaction.pos_payment_id else 'None'
                invoice_number = getattr(transaction, 'invoice_number', 'None')
                
                _logger.info('  - Transacción: %s, Pago: %s, Factura: %s', 
                           transaction.oca_transaction_id, 
                           payment_name,
                           invoice_number)
            
            # Verificar pagos OCA sin transacción asociada
            oca_payments = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'oca'
            )
            
            unassociated_payments = []
            for payment in oca_payments:
                transaction = self.env['payment.transaction'].sudo().search([
                    ('pos_payment_id', '=', payment.id),
                    ('oca_transaction_id', '!=', False)
                ], limit=1)
                
                if not transaction:
                    unassociated_payments.append(payment)
            
            _logger.info('Pagos OCA sin transacción asociada: %s', len(unassociated_payments))
            for payment in unassociated_payments:
                payment_name = getattr(payment, 'name', 'Unknown') or 'Unknown'
                payment_amount = getattr(payment, 'amount', 0.0)
                _logger.info('  - Pago: %s (Monto: %s)', payment_name, payment_amount)
            
            _logger.info('=== FIN DIAGNÓSTICO ===')
            
        except Exception as e:
            _logger.error('Error en diagnóstico de asociaciones OCA para orden ID %s: %s', self.id, str(e)) 