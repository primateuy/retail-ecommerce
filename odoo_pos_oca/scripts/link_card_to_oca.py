# -*- coding: utf-8 -*-
"""
Script para vincular manualmente el método de pago Card al proveedor OCA

Este script se puede ejecutar manualmente desde la consola de Odoo para
verificar y corregir la asociación del método Card al proveedor OCA.
"""

import logging

_logger = logging.getLogger(__name__)


def link_card_to_oca_provider(env):
    """
    Vincula manualmente el método de pago Card al proveedor OCA
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("=== INICIANDO VINCULACIÓN MANUAL DE MÉTODO CARD A PROVEEDOR OCA ===")
        
        # Buscar el proveedor de pago OCA
        oca_provider = env['payment.provider'].search([('code', '=', 'oca')], limit=1)
        
        if not oca_provider:
            _logger.error("❌ No se encontró el proveedor de pago OCA")
            return False
        
        _logger.info("✅ Proveedor OCA encontrado: %s (ID: %s)", oca_provider.name, oca_provider.id)
        _logger.info("📋 Métodos de pago actuales del proveedor OCA:")
        for pm in oca_provider.payment_method_ids:
            _logger.info("   - %s (código: %s, ID: %s)", pm.name, pm.code, pm.id)
        
        # Buscar el método de pago Card
        card_payment_method = env['payment.method'].search([('code', '=', 'card')], limit=1)
        
        if not card_payment_method:
            _logger.error("❌ No se encontró el método de pago Card")
            _logger.info("📋 Métodos de pago disponibles en el sistema:")
            all_methods = env['payment.method'].search([])
            for pm in all_methods:
                _logger.info("   - %s (código: %s, ID: %s)", pm.name, pm.code, pm.id)
            return False
        
        _logger.info("✅ Método Card encontrado: %s (ID: %s)", card_payment_method.name, card_payment_method.id)
        
        # Verificar si ya está vinculado
        if card_payment_method in oca_provider.payment_method_ids:
            _logger.info("ℹ️  El método de pago Card ya está vinculado al proveedor OCA")
            return True
        
        # Vincular el método Card al proveedor OCA
        _logger.info("🔗 Vinculando método Card al proveedor OCA...")
        
        # Obtener los IDs actuales
        current_method_ids = oca_provider.payment_method_ids.ids
        _logger.info("📋 IDs de métodos actuales: %s", current_method_ids)
        
        # Agregar el método Card
        new_method_ids = current_method_ids + [card_payment_method.id]
        _logger.info("📋 IDs de métodos después de agregar Card: %s", new_method_ids)
        
        # Actualizar el proveedor
        oca_provider.payment_method_ids = [(6, 0, new_method_ids)]
        
        # Verificar que la vinculación se hizo correctamente
        oca_provider.refresh()
        _logger.info("📋 Métodos de pago después de la vinculación:")
        for pm in oca_provider.payment_method_ids:
            _logger.info("   - %s (código: %s, ID: %s)", pm.name, pm.code, pm.id)
        
        if card_payment_method in oca_provider.payment_method_ids:
            _logger.info("✅ Método de pago Card vinculado exitosamente al proveedor OCA")
            return True
        else:
            _logger.error("❌ Error: El método Card no se vinculó correctamente al proveedor OCA")
            return False
            
    except Exception as e:
        _logger.error("❌ Error al vincular método de pago Card al proveedor OCA: %s", str(e))
        import traceback
        _logger.error("📋 Traceback completo: %s", traceback.format_exc())
        return False


def verify_oca_configuration(env):
    """
    Verifica la configuración completa del proveedor OCA
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("=== VERIFICANDO CONFIGURACIÓN COMPLETA DEL PROVEEDOR OCA ===")
        
        # Verificar proveedor OCA
        oca_provider = env['payment.provider'].search([('code', '=', 'oca')], limit=1)
        if oca_provider:
            _logger.info("✅ Proveedor OCA: %s (ID: %s, Estado: %s)", 
                        oca_provider.name, oca_provider.id, oca_provider.state)
        else:
            _logger.error("❌ Proveedor OCA no encontrado")
            return False
        
        # Verificar método OCA
        oca_method = env['payment.method'].search([('code', '=', 'oca')], limit=1)
        if oca_method:
            _logger.info("✅ Método OCA: %s (ID: %s)", oca_method.name, oca_method.id)
        else:
            _logger.error("❌ Método OCA no encontrado")
        
        # Verificar método Card
        card_method = env['payment.method'].search([('code', '=', 'card')], limit=1)
        if card_method:
            _logger.info("✅ Método Card: %s (ID: %s)", card_method.name, card_method.id)
        else:
            _logger.error("❌ Método Card no encontrado")
        
        # Verificar métodos asociados al proveedor
        _logger.info("📋 Métodos asociados al proveedor OCA:")
        for pm in oca_provider.payment_method_ids:
            _logger.info("   - %s (código: %s, ID: %s)", pm.name, pm.code, pm.id)
        
        return True
        
    except Exception as e:
        _logger.error("❌ Error al verificar configuración: %s", str(e))
        return False


# Función para ejecutar desde la consola de Odoo
def run_manual_link():
    """
    Función para ejecutar desde la consola de Odoo:
    
    from odoo_pos_oca.scripts.link_card_to_oca import run_manual_link
    run_manual_link()
    """
    env = self.env
    _logger.info("=== EJECUTANDO VINCULACIÓN MANUAL ===")
    
    # Verificar configuración
    verify_oca_configuration(env)
    
    # Vincular método Card
    success = link_card_to_oca_provider(env)
    
    if success:
        _logger.info("✅ Proceso completado exitosamente")
    else:
        _logger.error("❌ Proceso falló")
    
    return success 