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
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """
    Extensión del modelo payment.transaction para promociones OCA
    """
    _inherit = 'payment.transaction'

    @api.model
    def get_oca_display_message(self, oca_response):
        """
        Prioriza el texto de cancelación por incompatibilidad promo/lealtad sobre el mapa genérico 999.
        """
        if (
            oca_response
            and oca_response.get('promotion_incompatible_cancelled')
            and oca_response.get('msg')
        ):
            return oca_response['msg']
        return super().get_oca_display_message(oca_response)

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
            # Bloque: NO agregar línea de descuento aquí. El POS ya la insertó vía RPC
            # (add_promotion_discount_line) en processPromotionAndConfirm; volver a llamar
            # duplicaba el descuento y disparaba montos (-500, -300) y totales incorrectos.
        
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

            # Normalizar promotion_info para asegurar que sea un dict
            if isinstance(promotion_info, str):
                try:
                    promotion_info = json.loads(promotion_info) or {}
                except Exception as norm_error:
                    _logger.error(
                        'promotion_info almacenado como string no JSON para transacción %s: %s',
                        self.oca_transaction_id, str(norm_error)
                    )
                    promotion_info = {}
            
            if not promotion_info or not promotion_info.get('is_promotion'):
                return
            
            discount_amount = promotion_info.get('discount_amount', 0)
            product_id = promotion_info.get('product_id', False)
            description = promotion_info.get('description', 'Descuento Promoción')
            promotion_id = promotion_info.get('promotion_id', False)
            
            if discount_amount > 0 and product_id:
                # Verificar incompatibilidades antes de agregar la línea de descuento.
                # Si se detecta incompatibilidad, se lanza ValidationError para bloquear
                # el flujo de creación/validación de la orden POS y que el POS muestre
                # la validación al usuario sin continuar el proceso de pago.
                if promotion_id:
                    promotion = self.env['payment.method.promotion'].browse(promotion_id)
                    if promotion.exists():
                        applied_ids = []
                        if self.pos_order_id:
                            applied_ids = self.env[
                                'payment.method.promotion'
                            ].collect_applied_loyalty_program_ids_from_pos_order(
                                self.pos_order_id
                            )
                        blocked, block_msg = promotion.get_incompatibility_payment_block_for_applied_programs(
                            applied_ids
                        )
                        if blocked:
                            _logger.warning(
                                'No se puede aplicar promoción %s (ID: %s): %s',
                                promotion.name,
                                promotion.id,
                                block_msg,
                            )
                            raise ValidationError(block_msg)
                
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
        Sobrescribe write (sin agregar líneas de descuento: eso solo desde el POS por cobro).
        """
        return super().write(vals)
