# -*- coding: utf-8 -*-
"""
Extensión del modelo pos.payment para soporte de promociones OCA

Este módulo extiende pos.payment para:
- Priorizar transacciones con promoción al asociar transacciones OCA
"""

import logging
from datetime import datetime, timedelta

from odoo import models

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    """
    Extensión del modelo pos.payment para promociones OCA
    """
    _inherit = 'pos.payment'

    def _associate_oca_transaction(self):
        """
        Extiende el método base para priorizar transacciones con promoción
        
        En promociones, el monto de la transacción ($1290) NO coincide con el monto del pago ($1720)
        porque el descuento se aplica en el POS. Por lo tanto, debemos priorizar transacciones
        con promoción recientes sobre transacciones sin promoción con el mismo monto.
        """
        try:
            # Obtener los valores de forma segura
            payment_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            payment_amount = getattr(self, 'amount', 0.0)
            
            _logger.info('Buscando transacciones OCA para asociar con pago: %s (Monto: %s)', 
                        payment_name, payment_amount)
            
            # Buscar transacciones OCA sin pago asociado
            # Ordenar por fecha de creación descendente para priorizar las más recientes
            orphaned_transactions = self.env['payment.transaction'].sudo().search([
                ('oca_transaction_id', '!=', False),
                ('pos_payment_id', '=', False),
                ('state', 'in', ['pending', 'done'])
            ], order='create_date desc, id desc')
            
            if not orphaned_transactions:
                _logger.info('No se encontraron transacciones OCA huérfanas para asociar')
                return
            
            _logger.info('Encontradas %s transacciones OCA huérfanas para evaluar', len(orphaned_transactions))
            
            # Buscar transacción que coincida por monto
            # IMPORTANTE: Priorizar transacciones con promoción recientes
            matching_transaction = None
            best_score = 0
            five_minutes_ago = datetime.now() - timedelta(minutes=5)
            
            for transaction in orphaned_transactions:
                # Calcular score de coincidencia
                score = 0
                
                # Priorizar transacciones con promoción recientes (últimos 5 minutos)
                is_recent_promotion = (
                    transaction.is_promotion and 
                    transaction.create_date and 
                    transaction.create_date >= five_minutes_ago
                )
                
                if is_recent_promotion:
                    # Bonus alto para transacciones con promoción recientes
                    score += 200
                    _logger.info('Transacción con promoción reciente encontrada: %s (Monto: %s, Pago: %s)', 
                               transaction.oca_transaction_id, transaction.amount, payment_amount)
                
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
                
                # Bonus adicional para transacciones con promoción (aunque no coincida el monto)
                if transaction.is_promotion and not is_recent_promotion:
                    score += 75
                    _logger.info('Transacción con promoción encontrada: %s (Monto: %s, Pago: %s)', 
                               transaction.oca_transaction_id, transaction.amount, payment_amount)
                
                # Verificar que la transacción no esté ya asociada a otro pago
                if transaction.pos_payment_id:
                    existing_payment_name = getattr(transaction.pos_payment_id, 'name', 'Unknown') or 'Unknown'
                    _logger.info('Transacción %s ya asociada a pago %s, saltando...', 
                               transaction.oca_transaction_id, existing_payment_name)
                    continue
                
                # Si es la mejor coincidencia hasta ahora, guardarla
                if score > best_score:
                    best_score = score
                    matching_transaction = transaction
                    _logger.info('Nueva mejor coincidencia: Transacción %s (Score: %s, is_promotion: %s)', 
                               transaction.oca_transaction_id, score, transaction.is_promotion)
            
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
                _logger.info('Transacción OCA asociada exitosamente: %s -> Pago: %s, Orden: %s (Score: %s, is_promotion: %s)', 
                           matching_transaction.oca_transaction_id, payment_name, order_name, best_score, matching_transaction.is_promotion)
            else:
                _logger.warning('No se encontró transacción OCA para el pago: %s (Monto: %s)', 
                              payment_name, payment_amount)
            
        except Exception as e:
            _logger.error('Error al asociar transacción OCA con pago ID %s: %s', self.id, str(e))
            import traceback
            _logger.error('Traceback: %s', traceback.format_exc())
