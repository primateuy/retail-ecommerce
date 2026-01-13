# -*- coding: utf-8 -*-
"""
Extensión del modelo payment.transaction para soporte de promociones OCA

Este módulo extiende payment.transaction para:
- Almacenar información de promoción en las transacciones OCA
- Procesar información de promoción al crear/actualizar transacciones
"""

import json
import logging

from odoo import models, api

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """
    Extensión del modelo payment.transaction para promociones OCA
    """
    _inherit = 'payment.transaction'

    def update_oca_transaction(self, oca_response):
        """
        Extiende el método base para incluir información de promoción
        """
        # Llamar al método base primero
        super().update_oca_transaction(oca_response)
        
        # Procesar información de promoción si está presente
        if oca_response.get('promotion_info'):
            promotion_info = oca_response['promotion_info']
            update_vals = {
                'is_promotion': promotion_info.get('is_promotion', False),
            }
            
            # Actualizar oca_complete_response para incluir información de promoción
            try:
                complete_response = json.loads(self.oca_complete_response or '{}')
                complete_response['promotion_info'] = promotion_info
                update_vals['oca_complete_response'] = json.dumps(complete_response, indent=2, ensure_ascii=False)
            except Exception as e:
                _logger.error('Error al actualizar oca_complete_response con información de promoción: %s', str(e))
            
            self.write(update_vals)
            _logger.info('Información de promoción actualizada en transacción OCA: %s', self.oca_transaction_id)

    @api.model
    def create_oca_transaction_with_complete_data(self, oca_response, pos_order=None, pos_payment=None, transaction_id=None):
        """
        Extiende el método base para incluir información de promoción al crear transacciones
        """
        # Llamar al método base primero
        transaction = super().create_oca_transaction_with_complete_data(
            oca_response, pos_order, pos_payment, transaction_id
        )
        
        # Procesar información de promoción si está presente
        if oca_response.get('promotion_info'):
            promotion_info = oca_response['promotion_info']
            update_vals = {
                'is_promotion': promotion_info.get('is_promotion', False),
            }
            
            # Actualizar oca_complete_response para incluir información de promoción
            try:
                complete_response = json.loads(transaction.oca_complete_response or '{}')
                complete_response['promotion_info'] = promotion_info
                update_vals['oca_complete_response'] = json.dumps(complete_response, indent=2, ensure_ascii=False)
            except Exception as e:
                _logger.error('Error al actualizar oca_complete_response con información de promoción: %s', str(e))
            
            transaction.write(update_vals)
            _logger.info('Información de promoción almacenada en transacción OCA creada: %s', transaction.oca_transaction_id)
            
            # Si la transacción tiene una orden asociada, intentar agregar la línea de descuento
            if transaction.pos_order_id and promotion_info.get('is_promotion'):
                transaction._add_promotion_discount_to_order()
        
        return transaction
    
    def _add_promotion_discount_to_order(self):
        """
        Agrega la línea de descuento de promoción a la orden POS asociada
        
        Este método se llama cuando una transacción con promoción se asocia con una orden POS
        """
        self.ensure_one()
        
        if not self.pos_order_id or not self.is_promotion:
            return
        
        try:
            import json
            complete_response = json.loads(self.oca_complete_response or '{}')
            promotion_info = complete_response.get('promotion_info', {})
            
            if not promotion_info or not promotion_info.get('is_promotion'):
                return
            
            discount_amount = promotion_info.get('discount_amount', 0)
            product_id = promotion_info.get('product_id', False)
            description = promotion_info.get('description', 'Descuento Promoción')
            promotion_id = promotion_info.get('promotion_id', False)
            
            if discount_amount > 0 and product_id:
                # Verificar incompatibilidades antes de agregar la línea de descuento
                if promotion_id:
                    promotion = self.env['payment.method.promotion'].browse(promotion_id)
                    if promotion.exists():
                        is_incompatible, incompatible_promotions, incompat_msg = promotion._check_incompatibilities(self.pos_order_id)
                        if is_incompatible:
                            _logger.warning('No se puede aplicar promoción %s (ID: %s) porque es incompatible con: %s. %s', 
                                          promotion.name, promotion.id, 
                                          ', '.join([p.name for p in incompatible_promotions]),
                                          incompat_msg)
                            return
                
                # Agregar línea de descuento a la orden
                discount_result = self.pos_order_id.add_promotion_discount_line(
                    discount_amount,
                    product_id,
                    description,
                    promotion_id=promotion_id
                )
                
                if discount_result.get('success'):
                    _logger.info('Línea de descuento de promoción agregada a orden %s desde transacción OCA %s (Descuento: %s)', 
                               self.pos_order_id.name, self.oca_transaction_id, discount_amount)
                else:
                    _logger.error('Error al agregar línea de descuento a orden %s: %s', 
                                self.pos_order_id.name, discount_result.get('error'))
        except Exception as e:
            _logger.error('Error al agregar línea de descuento de promoción a orden: %s', str(e))
            import traceback
            _logger.error('Traceback: %s', traceback.format_exc())
    
    def write(self, vals):
        """
        Sobrescribe write para agregar línea de descuento cuando se asocia la transacción con una orden
        """
        # Verificar si se está asociando con una orden ANTES de escribir
        # para poder acceder a self.is_promotion antes de que cambie
        should_add_discount = False
        pos_order_id_to_check = None
        
        if 'pos_order_id' in vals and vals.get('pos_order_id'):
            # Verificar si la transacción es una promoción ANTES de escribir
            # (porque después de escribir, self.is_promotion podría cambiar)
            if self.is_promotion:
                should_add_discount = True
                pos_order_id_to_check = vals['pos_order_id']
        
        result = super().write(vals)
        
        # Si se debe agregar el descuento, hacerlo después de escribir
        if should_add_discount and pos_order_id_to_check:
            try:
                pos_order = self.env['pos.order'].browse(pos_order_id_to_check)
                if pos_order.exists():
                    _logger.info('Transacción OCA %s asociada con orden %s, agregando descuento de promoción', 
                               self.oca_transaction_id, pos_order.name)
                    self._add_promotion_discount_to_order()
            except Exception as e:
                _logger.error('Error al agregar descuento después de asociar transacción con orden: %s', str(e))
                import traceback
                _logger.error('Traceback: %s', traceback.format_exc())
        
        return result
