# -*- coding: utf-8 -*-
"""
Script de post-migración para el módulo OCA POS

Este script se ejecuta después de la migración para asegurar que todas las
configuraciones necesarias se apliquen correctamente.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Script de migración que se ejecuta después de actualizar el módulo
    
    Args:
        cr: Cursor de la base de datos
        version: Versión a la que se está migrando
    """
    _logger.info("Iniciando post-migración del módulo OCA POS versión %s", version)
    
    try:
        # Vincular método Card al proveedor OCA
        _link_card_to_oca_provider(cr)
        
        _logger.info("Post-migración del módulo OCA POS completada exitosamente")
        
    except Exception as e:
        _logger.error("Error durante la post-migración del módulo OCA POS: %s", str(e))
        # No lanzar la excepción para evitar que falle la migración


def _link_card_to_oca_provider(cr):
    """
    Vincula el método de pago Card al proveedor OCA
    
    Args:
        cr: Cursor de la base de datos
    """
    try:
        _logger.info("Vinculando método Card al proveedor OCA")
        
        # Obtener el ID del proveedor OCA
        cr.execute("""
            SELECT id FROM payment_provider 
            WHERE code = 'oca' 
            LIMIT 1
        """)
        
        provider_result = cr.fetchone()
        if not provider_result:
            _logger.warning("No se encontró el proveedor de pago OCA")
            return
        
        provider_id = provider_result[0]
        _logger.info("Proveedor OCA encontrado con ID: %s", provider_id)
        
        # Obtener el ID del método de pago OCA
        cr.execute("""
            SELECT id FROM payment_method 
            WHERE code = 'oca' 
            LIMIT 1
        """)
        
        oca_method_result = cr.fetchone()
        if not oca_method_result:
            _logger.warning("No se encontró el método de pago OCA")
            return
        
        oca_method_id = oca_method_result[0]
        _logger.info("Método OCA encontrado con ID: %s", oca_method_id)
        
        # Obtener el ID del método de pago Card (creado por el core de Odoo)
        cr.execute("""
            SELECT id FROM payment_method 
            WHERE code = 'card' 
            LIMIT 1
        """)
        
        card_result = cr.fetchone()
        if not card_result:
            _logger.warning("No se encontró el método de pago Card (debe estar creado por el core de Odoo)")
            return
        
        card_id = card_result[0]
        _logger.info("Método Card encontrado con ID: %s", card_id)
        
        # Obtener los métodos actuales del proveedor
        cr.execute("""
            SELECT payment_method_id FROM payment_provider_payment_method_rel 
            WHERE payment_provider_id = %s
        """, (provider_id,))
        
        current_methods = [row[0] for row in cr.fetchall()]
        _logger.info("Métodos actuales del proveedor OCA: %s", current_methods)
        
        # Crear la lista de métodos que debe tener (OCA + Card)
        required_methods = [oca_method_id, card_id]
        _logger.info("Métodos requeridos para el proveedor OCA: %s", required_methods)
        
        # Verificar si ya tiene todos los métodos requeridos
        if set(current_methods) == set(required_methods):
            _logger.info("El proveedor OCA ya tiene todos los métodos requeridos")
            return
        
        # Actualizar el proveedor con los métodos requeridos
        _logger.info("Actualizando proveedor OCA con métodos: %s", required_methods)
        
        # Usar el comando (6, 0, ids) para reemplazar completamente
        cr.execute("""
            UPDATE payment_provider 
            SET payment_method_ids = %s
            WHERE id = %s
        """, (str(required_methods), provider_id))
        
        # Limpiar la tabla de relación y recrear
        cr.execute("""
            DELETE FROM payment_provider_payment_method_rel 
            WHERE payment_provider_id = %s
        """, (provider_id,))
        
        # Insertar las nuevas relaciones
        for method_id in required_methods:
            cr.execute("""
                INSERT INTO payment_provider_payment_method_rel (
                    payment_provider_id, payment_method_id
                ) VALUES (%s, %s)
            """, (provider_id, method_id))
        
        _logger.info("Método de pago Card vinculado exitosamente al proveedor OCA")
        
        # Verificar que la vinculación se hizo correctamente
        cr.execute("""
            SELECT COUNT(*) FROM payment_provider_payment_method_rel 
            WHERE payment_provider_id = %s
        """, (provider_id,))
        
        count_result = cr.fetchone()
        if count_result:
            _logger.info("El proveedor OCA tiene %s métodos de pago asociados", count_result[0])
            
    except Exception as e:
        _logger.error("Error al vincular método Card al proveedor OCA: %s", str(e))
        import traceback
        _logger.error("Traceback completo: %s", traceback.format_exc()) 