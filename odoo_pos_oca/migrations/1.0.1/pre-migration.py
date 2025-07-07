# -*- coding: utf-8 -*-
"""
Script de pre-migración para el módulo OCA POS

Este script se ejecuta antes de la migración para asegurar que todas las
configuraciones necesarias estén en su lugar.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Script de migración que se ejecuta antes de actualizar el módulo
    
    Args:
        cr: Cursor de la base de datos
        version: Versión a la que se está migrando
    """
    _logger.info("Iniciando pre-migración del módulo OCA POS versión %s", version)
    
    try:
        # Asegurar que el proveedor OCA esté configurado
        _ensure_oca_provider(cr)
        
        # Vincular método Card al proveedor OCA
        _link_card_to_oca_provider(cr)
        
        _logger.info("Pre-migración del módulo OCA POS completada exitosamente")
        
    except Exception as e:
        _logger.error("Error durante la pre-migración del módulo OCA POS: %s", str(e))
        # No lanzar la excepción para evitar que falle la migración


def _ensure_oca_provider(cr):
    """
    Asegura que el proveedor de pago OCA esté configurado
    
    Args:
        cr: Cursor de la base de datos
    """
    try:
        _logger.info("Verificando proveedor de pago OCA")
        
        # Verificar si el proveedor OCA ya existe
        cr.execute("""
            SELECT id FROM payment_provider 
            WHERE code = 'oca' 
            LIMIT 1
        """)
        
        if not cr.fetchone():
            _logger.info("Creando proveedor de pago OCA")
            
            # Crear el proveedor de pago OCA
            cr.execute("""
                INSERT INTO payment_provider (
                    name, code, state, allow_tokenization, company_id,
                    create_uid, create_date, write_uid, write_date
                ) VALUES (
                    'OCA', 'oca', 'test', true, 1,
                    1, NOW(), 1, NOW()
                )
            """)
            
            _logger.info("Proveedor de pago OCA creado exitosamente")
        else:
            _logger.info("Proveedor de pago OCA ya existe")
            
    except Exception as e:
        _logger.error("Error al verificar/crear proveedor de pago OCA: %s", str(e))


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
        
        # Verificar si ya están vinculados
        cr.execute("""
            SELECT payment_provider_id FROM payment_provider_payment_method_rel 
            WHERE payment_provider_id = %s AND payment_method_id = %s
        """, (provider_id, card_id))
        
        if not cr.fetchone():
            # Vincular el método Card al proveedor OCA
            cr.execute("""
                INSERT INTO payment_provider_payment_method_rel (
                    payment_provider_id, payment_method_id
                ) VALUES (%s, %s)
            """, (provider_id, card_id))
            
            _logger.info("Método de pago Card vinculado exitosamente al proveedor OCA")
        else:
            _logger.info("El método de pago Card ya está vinculado al proveedor OCA")
            
    except Exception as e:
        _logger.error("Error al vincular método Card al proveedor OCA: %s", str(e)) 