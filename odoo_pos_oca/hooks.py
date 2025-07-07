# -*- coding: utf-8 -*-
"""
Hooks para la instalación y actualización del módulo OCA POS

Este archivo contiene funciones que se ejecutan durante la instalación
y actualización del módulo para asegurar que todas las configuraciones
se apliquen correctamente.
"""

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Hook que se ejecuta después de la instalación del módulo
    
    Este hook asegura que todas las configuraciones necesarias se apliquen
    correctamente durante la instalación del módulo.
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("Iniciando post-instalación del módulo OCA POS")
        
        # Asegurar que el proveedor de pago OCA esté configurado
        _ensure_oca_provider(env)
        
        # Asegurar que el diario de pago OCA esté configurado
        _ensure_oca_journal(env)
        
        # Asegurar que el método de pago POS OCA esté configurado
        _ensure_oca_pos_payment_method(env)
        
        # Vincular método de pago Card al proveedor OCA
        _link_card_payment_method_to_oca(env)
        
        _logger.info("Post-instalación del módulo OCA POS completada exitosamente")
        
    except Exception as e:
        _logger.error("Error durante la post-instalación del módulo OCA POS: %s", str(e))
        # No lanzar la excepción para evitar que falle la instalación del módulo


def _ensure_oca_provider(env):
    """
    Asegura que el proveedor de pago OCA esté configurado correctamente
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("Verificando configuración del proveedor de pago OCA")
        
        # Buscar el proveedor OCA
        provider = env['payment.provider'].search([('code', '=', 'oca')], limit=1)
        
        if not provider:
            _logger.warning("No se encontró el proveedor de pago OCA. Creando...")
            
            # Buscar el método de pago OCA
            payment_method = env['payment.method'].search([('code', '=', 'oca')], limit=1)
            
            if payment_method:
                # Crear el proveedor OCA
                provider = env['payment.provider'].create({
                    'name': 'OCA',
                    'code': 'oca',
                    'state': 'test',
                    'allow_tokenization': True,
                    'payment_method_ids': [(6, 0, [payment_method.id])],
                    'company_id': env.company.id,
                })
                _logger.info("Proveedor de pago OCA creado exitosamente")
            else:
                _logger.error("No se encontró el método de pago OCA para crear el proveedor")
        else:
            _logger.info("Proveedor de pago OCA ya existe")
            
    except Exception as e:
        _logger.error("Error al configurar el proveedor de pago OCA: %s", str(e))


def _ensure_oca_journal(env):
    """
    Asegura que el diario de pago OCA esté configurado correctamente
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("Verificando configuración del diario de pago OCA")
        
        # Buscar el diario OCA
        journal = env['account.journal'].search([('code', '=', 'OCA')], limit=1)
        
        if not journal:
            _logger.warning("No se encontró el diario de pago OCA. Creando...")
            
            # Buscar el método de pago de cuenta OCA
            account_payment_method = env['account.payment.method'].search([('code', '=', 'oca')], limit=1)
            
            if account_payment_method:
                # Crear el diario OCA
                journal = env['account.journal'].create({
                    'name': 'OCA',
                    'code': 'OCA',
                    'type': 'bank',
                    'company_id': env.company.id,
                    'currency_id': env.ref('base.UYU').id,
                    'inbound_payment_method_ids': [(6, 0, [account_payment_method.id])],
                    'outbound_payment_method_ids': [(6, 0, [account_payment_method.id])],
                })
                _logger.info("Diario de pago OCA creado exitosamente")
            else:
                _logger.error("No se encontró el método de pago de cuenta OCA para crear el diario")
        else:
            _logger.info("Diario de pago OCA ya existe")
            
    except Exception as e:
        _logger.error("Error al configurar el diario de pago OCA: %s", str(e))


def _ensure_oca_pos_payment_method(env):
    """
    Asegura que el método de pago POS OCA esté configurado correctamente
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("Verificando configuración del método de pago POS OCA")
        
        # Buscar el método de pago POS OCA
        pos_payment_method = env['pos.payment.method'].search([('use_payment_terminal', '=', 'oca')], limit=1)
        
        if not pos_payment_method:
            _logger.warning("No se encontró el método de pago POS OCA. Creando...")
            
            # Buscar la cuenta por cobrar
            receivable_account = env['account.account'].search([
                ('account_type', '=', 'asset_receivable'),
                ('company_id', '=', env.company.id)
            ], limit=1)
            
            if receivable_account:
                # Crear el método de pago POS OCA
                pos_payment_method = env['pos.payment.method'].create({
                    'name': 'OCA',
                    'use_payment_terminal': 'oca',
                    'receivable_account_id': receivable_account.id,
                    'is_cash_count': False,
                    'active': True,
                    'sequence': 10,
                    'url_webservice': 'https://api.oca.com',
                    'codigo_sistema': '1',
                    'codigo_terminal': '001',
                    'client_app_id': '1',
                    'codigo_sucursal': 1,
                })
                _logger.info("Método de pago POS OCA creado exitosamente")
            else:
                _logger.error("No se encontró la cuenta por cobrar para crear el método de pago POS")
        else:
            _logger.info("Método de pago POS OCA ya existe")
            
    except Exception as e:
        _logger.error("Error al configurar el método de pago POS OCA: %s", str(e))


def _link_card_payment_method_to_oca(env):
    """
    Vincula el método de pago Card al proveedor de pago OCA
    
    Este método busca el método de pago Card existente (creado por el core de Odoo)
    y lo asocia al proveedor OCA para permitir el procesamiento de transacciones
    con tarjeta a través de OCA.
    
    Args:
        env: Entorno de Odoo
    """
    try:
        _logger.info("Vinculando método de pago Card al proveedor OCA")
        
        # Buscar el proveedor de pago OCA
        oca_provider = env['payment.provider'].search([('code', '=', 'oca')], limit=1)
        
        if not oca_provider:
            _logger.warning("No se encontró el proveedor de pago OCA para vincular el método Card")
            return
        
        _logger.info("Proveedor OCA encontrado: %s (ID: %s)", oca_provider.name, oca_provider.id)
        _logger.info("Métodos de pago actuales del proveedor OCA: %s", 
                    [pm.name for pm in oca_provider.payment_method_ids])
        
        # Buscar el método de pago Card existente (creado por el core de Odoo)
        card_payment_method = env['payment.method'].search([('code', '=', 'card')], limit=1)
        
        if not card_payment_method:
            _logger.warning("No se encontró el método de pago Card (debe estar creado por el core de Odoo)")
            # Listar todos los métodos de pago disponibles para debug
            all_methods = env['payment.method'].search([])
            _logger.info("Métodos de pago disponibles: %s", 
                        [(pm.name, pm.code) for pm in all_methods])
            return
        
        _logger.info("Método Card encontrado: %s (ID: %s)", card_payment_method.name, card_payment_method.id)
        
        # Verificar si el método Card ya está vinculado al proveedor OCA
        if card_payment_method in oca_provider.payment_method_ids:
            _logger.info("El método de pago Card ya está vinculado al proveedor OCA")
            return
        
        # Vincular el método Card al proveedor OCA
        _logger.info("Vinculando método Card (ID: %s) al proveedor OCA (ID: %s)", 
                    card_payment_method.id, oca_provider.id)
        
        # Usar el comando (4, id) para agregar sin reemplazar
        oca_provider.payment_method_ids = [(4, card_payment_method.id)]
        
        # Verificar que la vinculación se hizo correctamente
        oca_provider.refresh()
        _logger.info("Métodos de pago después de la vinculación: %s", 
                    [pm.name for pm in oca_provider.payment_method_ids])
        
        if card_payment_method in oca_provider.payment_method_ids:
            _logger.info("Método de pago Card vinculado exitosamente al proveedor OCA")
        else:
            _logger.error("Error: El método Card no se vinculó correctamente al proveedor OCA")
            
    except Exception as e:
        _logger.error("Error al vincular método de pago Card al proveedor OCA: %s", str(e))
        import traceback
        _logger.error("Traceback completo: %s", traceback.format_exc()) 