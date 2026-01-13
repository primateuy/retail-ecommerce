# -*- coding: utf-8 -*-
"""
Modelo para configurar promociones por método de pago

Este modelo permite configurar promociones que se aplican automáticamente
cuando se utiliza un proveedor de pago específico con un medio de pago determinado (BIN).
"""

import logging
from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentMethodPromotion(models.Model):
    """
    Modelo para configurar promociones por método de pago
    
    Permite definir:
    - Producto de descuento
    - Porcentaje de descuento
    - Proveedor de pago (OCA, Stripe, Mercado Pago, etc.)
    - BINs habilitados
    - Promociones incompatibles
    - Vigencia (fechas, compañía)
    """
    _name = 'payment.method.promotion'
    _description = 'Promoción por Método de Pago'
    _order = 'sequence, name'

    name = fields.Char(
        string='Nombre de la Promoción',
        required=True,
        help='Nombre descriptivo de la promoción (ej: "Descuento 25% OCA Visa")'
    )
    
    active = fields.Boolean(
        string='Activa',
        default=True,
        help='Si está desactivada, la promoción no se evaluará'
    )
    
    sequence = fields.Integer(
        string='Secuencia',
        default=10,
        help='Orden de evaluación (menor número = mayor prioridad)'
    )
    
    # Configuración de descuento
    discount_product_id = fields.Many2one(
        'product.product',
        string='Producto de Descuento',
        required=True,
        domain=[('sale_ok', '=', True)],
        help='Producto utilizado para registrar el descuento en el ticket/factura'
    )
    
    discount_percent = fields.Float(
        string='Porcentaje de Descuento',
        required=True,
        digits=(16, 2),
        help='Porcentaje de descuento que se aplica sobre el total de la orden'
    )
    
    discount_type = fields.Selection(
        selection=[
            ('percentage', 'Porcentaje sobre Total'),
            ('percentage_untaxed', 'Porcentaje sobre Subtotal (sin impuestos)'),
        ],
        string='Tipo de Descuento',
        default='percentage',
        required=True,
        help='Base sobre la cual se calcula el porcentaje de descuento'
    )
    
    # Configuración de proveedor y método de pago
    payment_provider_id = fields.Many2one(
        'payment.provider',
        string='Proveedor de Pago (Web)',
        help='Proveedor de pago en el que aplica esta promoción (para ventas web/eCommerce)'
    )
    
    payment_method_id = fields.Many2one(
        'pos.payment.method',
        string='Método de Pago (POS)',
        help='Método de pago POS en el que aplica esta promoción'
    )
    
    # Validación de BINs
    bin_ids = fields.One2many(
        'payment.method.promotion.bin',
        'promotion_id',
        string='BINs Habilitados',
        help='Lista de BINs (primeros dígitos de tarjeta) que habilitan esta promoción. '
             'Si está vacío, aplica a todas las tarjetas del proveedor.'
    )
    
    require_bin_validation = fields.Boolean(
        string='Requiere Validación de BIN',
        default=True,
        help='Si está activado, solo aplica si el BIN de la tarjeta está en la lista. '
             'Si está desactivado, aplica a todas las tarjetas del proveedor.'
    )
    
    # Promociones incompatibles
    incompatible_promotion_ids = fields.Many2many(
        'payment.method.promotion',
        'promotion_incompatible_rel',
        'promotion_id',
        'incompatible_id',
        string='Promociones Incompatibles',
        help='Lista de promociones que no pueden combinarse con esta. '
             'Si el pedido ya tiene una promoción incompatible aplicada, esta no se aplicará.'
    )
    
    # Vigencia
    date_from = fields.Date(
        string='Válida desde',
        help='Fecha desde la cual la promoción está activa'
    )
    
    date_to = fields.Date(
        string='Válida hasta',
        help='Fecha hasta la cual la promoción está activa'
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company,
        help='Compañía para la cual aplica esta promoción'
    )
    
    # Campos adicionales
    description = fields.Text(
        string='Descripción',
        help='Descripción adicional de la promoción'
    )
    
    # Estadísticas (opcional, para reportes)
    times_applied = fields.Integer(
        string='Veces Aplicada',
        default=0,
        readonly=True,
        help='Contador de veces que se ha aplicado esta promoción'
    )

    @api.constrains('discount_percent')
    def _check_discount_percent(self):
        """
        Valida que el porcentaje de descuento esté en un rango válido
        """
        for record in self:
            if record.discount_percent <= 0:
                raise ValidationError(_('El porcentaje de descuento debe ser mayor a 0'))
            if record.discount_percent > 100:
                raise ValidationError(_('El porcentaje de descuento no puede ser mayor a 100%'))
    
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        """
        Valida que la fecha de inicio sea anterior a la fecha de fin
        """
        for record in self:
            if record.date_from and record.date_to:
                if record.date_from > record.date_to:
                    raise ValidationError(_('La fecha de inicio debe ser anterior a la fecha de fin'))
    
    @api.constrains('payment_provider_id', 'payment_method_id')
    def _check_payment_config(self):
        """
        Valida que se configure al menos un proveedor o método de pago
        """
        for record in self:
            if not record.payment_provider_id and not record.payment_method_id:
                raise ValidationError(_('Debe configurar al menos un Proveedor de Pago (Web) o Método de Pago (POS)'))
    
    def _is_valid_date(self):
        """
        Verifica si la promoción está vigente según las fechas
        
        Returns:
            bool: True si está vigente, False en caso contrario
        """
        self.ensure_one()
        today = date.today()
        
        if self.date_from and today < self.date_from:
            return False
        
        if self.date_to and today > self.date_to:
            return False
        
        return True
    
    def _matches_bin(self, card_number):
        """
        Verifica si el BIN de la tarjeta coincide con alguno de los BINs configurados
        
        Args:
            card_number (str): Número de tarjeta completo o BIN
            
        Returns:
            bool: True si coincide o si no requiere validación de BIN, False en caso contrario
        """
        self.ensure_one()
        
        # Si no requiere validación de BIN, aplicar a todas las tarjetas
        if not self.require_bin_validation:
            return True
        
        # Si no hay BINs configurados y requiere validación, no aplicar
        if not self.bin_ids:
            return False
        
        # Extraer BIN del número de tarjeta (primeros 6 dígitos típicamente)
        # El CardNumber puede venir como "542991******1207" o "542991030"
        card_clean = str(card_number).replace('*', '').replace(' ', '').strip()
        
        # Si el número tiene menos de 6 dígitos, usar lo que tenga
        bin_length = min(6, len(card_clean))
        card_bin = card_clean[:bin_length] if card_clean else ''
        
        if not card_bin:
            return False
        
        # Verificar si el BIN coincide con alguno de los configurados
        for bin_record in self.bin_ids:
            bin_clean = str(bin_record.name).replace('*', '').replace(' ', '').strip()
            # Comparar los primeros dígitos
            min_length = min(len(card_bin), len(bin_clean))
            if card_bin[:min_length] == bin_clean[:min_length]:
                return True
        
        return False
    
    def _matches_payment_provider(self, provider_code=None, payment_method_id=None):
        """
        Verifica si la promoción aplica para el proveedor/método de pago dado
        
        Args:
            provider_code (str): Código del proveedor de pago (ej: 'oca', 'stripe')
            payment_method_id (int): ID del método de pago POS
            
        Returns:
            bool: True si coincide, False en caso contrario
        """
        self.ensure_one()
        
        # Verificar proveedor de pago web
        if provider_code and self.payment_provider_id:
            if self.payment_provider_id.code == provider_code:
                return True
        
        # Verificar método de pago POS
        if payment_method_id and self.payment_method_id:
            if self.payment_method_id.id == payment_method_id:
                return True
        
        return False
    
    def _check_incompatibilities(self, order):
        """
        Verifica si hay promociones incompatibles ya aplicadas en la orden
        
        Args:
            order: Registro de pos.order o sale.order
            
        Returns:
            tuple: (is_incompatible: bool, incompatible_promotions: list, message: str)
        """
        self.ensure_one()
        
        incompatible_promotions = []
        
        # Si no hay promociones incompatibles configuradas, no hay conflicto
        if not self.incompatible_promotion_ids:
            return False, incompatible_promotions, ''
        
        # Buscar promociones aplicadas en esta orden a través de las transacciones de pago
        # Las transacciones OCA con promoción almacenan el promotion_id en oca_complete_response
        if hasattr(order, 'payment_ids'):
            # Orden POS
            for payment in order.payment_ids:
                if payment.payment_transaction_id and payment.payment_transaction_id.is_promotion:
                    transaction = payment.payment_transaction_id
                    try:
                        import json
                        complete_response = json.loads(transaction.oca_complete_response or '{}')
                        promotion_info = complete_response.get('promotion_info', {})
                        applied_promotion_id = promotion_info.get('promotion_id', False)
                        
                        if applied_promotion_id:
                            applied_promotion = self.browse(applied_promotion_id)
                            if applied_promotion.exists() and applied_promotion in self.incompatible_promotion_ids:
                                incompatible_promotions.append(applied_promotion)
                    except Exception as e:
                        _logger.warning('Error al verificar incompatibilidades en transacción %s: %s', 
                                      transaction.id, str(e))
        
        # También buscar en las líneas de descuento de la orden
        # Si hay líneas de descuento con el producto de alguna promoción incompatible, considerar incompatibilidad
        if hasattr(order, 'lines'):
            for line in order.lines:
                if line.product_id and line.price_unit < 0:  # Línea de descuento
                    # Buscar promociones que usen este producto de descuento y sean incompatibles
                    for incompatible_promotion in self.incompatible_promotion_ids:
                        if incompatible_promotion.discount_product_id.id == line.product_id.id:
                            if incompatible_promotion not in incompatible_promotions:
                                incompatible_promotions.append(incompatible_promotion)
        
        if incompatible_promotions:
            message = _('Esta promoción no puede combinarse con: %s') % ', '.join([p.name for p in incompatible_promotions])
            return True, incompatible_promotions, message
        
        return False, incompatible_promotions, ''
    
    @api.model
    def find_applicable_promotion(self, card_data, provider_code=None, payment_method_id=None, order=None):
        """
        Busca una promoción aplicable según los criterios dados
        
        Este método evalúa todas las promociones activas y retorna la primera que cumpla
        todos los criterios (proveedor, BIN, fechas, incompatibilidades).
        
        Args:
            card_data (dict): Datos de la tarjeta con keys:
                - Acquirer: Adquirente
                - Issuer: Emisor
                - CardNumber: Número de tarjeta o BIN
            provider_code (str): Código del proveedor de pago
            payment_method_id (int): ID del método de pago POS
            order: Registro de pos.order o sale.order para validar incompatibilidades
            
        Returns:
            payment.method.promotion o None: Promoción aplicable o None si no hay ninguna
        """
        # Buscar promociones activas
        domain = [
            ('active', '=', True),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.env.company.id),
        ]
        
        promotions = self.search(domain, order='sequence, id')
        
        card_number = card_data.get('CardNumber', '') or ''
        
        for promotion in promotions:
            # Verificar fechas de vigencia
            if not promotion._is_valid_date():
                continue
            
            # Verificar proveedor/método de pago
            if not promotion._matches_payment_provider(provider_code, payment_method_id):
                continue
            
            # Verificar BIN
            if not promotion._matches_bin(card_number):
                continue
            
            # Verificar incompatibilidades
            if order:
                is_incompatible, _, _ = promotion._check_incompatibilities(order)
                if is_incompatible:
                    continue
            
            # Si llegamos aquí, la promoción es aplicable
            _logger.info('Promoción aplicable encontrada: %s (ID: %s)', promotion.name, promotion.id)
            return promotion
        
        return None
    
    def action_increment_times_applied(self):
        """
        Incrementa el contador de veces aplicada
        """
        self.ensure_one()
        self.times_applied += 1
