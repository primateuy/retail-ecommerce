# -*- coding: utf-8 -*-
"""
Modelo para almacenar BINs (Bank Identification Numbers) de promociones

Los BINs son los primeros dígitos de una tarjeta que identifican el banco emisor.
Este modelo permite configurar qué BINs habilitan una promoción específica.
"""

import logging
import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentMethodPromotionBin(models.Model):
    """
    Modelo para almacenar BINs de promociones
    
    Un BIN (Bank Identification Number) son los primeros dígitos de una tarjeta
    que identifican el banco emisor. Típicamente son los primeros 6 dígitos.
    """
    _name = 'payment.method.promotion.bin'
    _description = 'BIN de Promoción por Método de Pago'
    _order = 'promotion_id, name'

    name = fields.Char(
        string='BIN',
        required=True,
        help='Primeros dígitos de la tarjeta que habilitan la promoción. '
             'Ejemplos: "542991" (Visa), "541234" (Mastercard). '
             'Puede incluir asteriscos como comodines: "542***"'
    )
    
    promotion_id = fields.Many2one(
        'payment.method.promotion',
        string='Promoción',
        required=True,
        ondelete='cascade',
        help='Promoción a la que pertenece este BIN'
    )
    
    description = fields.Char(
        string='Descripción',
        help='Descripción opcional del BIN (ej: "Visa Crédito Banco X")'
    )
    
    active = fields.Boolean(
        string='Activo',
        default=True,
        help='Si está desactivado, este BIN no se considerará para la promoción'
    )

    @api.constrains('name')
    def _check_bin_format(self):
        """
        Valida que el BIN tenga un formato válido (solo dígitos y asteriscos)
        """
        for record in self:
            if not record.name:
                continue
            
            # Permitir dígitos, asteriscos y espacios (que se limpiarán)
            bin_clean = str(record.name).replace(' ', '').replace('*', '').strip()
            
            if not bin_clean:
                raise ValidationError(_('El BIN no puede estar vacío'))
            
            # Verificar que solo contenga dígitos (después de limpiar asteriscos)
            if not re.match(r'^\d+$', bin_clean):
                raise ValidationError(_('El BIN debe contener solo dígitos (0-9) y opcionalmente asteriscos (*) como comodines'))
            
            # El BIN típicamente tiene entre 4 y 8 dígitos
            if len(bin_clean) < 4:
                raise ValidationError(_('El BIN debe tener al menos 4 dígitos'))
            
            if len(bin_clean) > 8:
                raise ValidationError(_('El BIN no debe tener más de 8 dígitos (típicamente son 6)'))
