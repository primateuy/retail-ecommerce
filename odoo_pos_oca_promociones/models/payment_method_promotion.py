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
    
    # Configuración por proveedor de pago: aplica a todos los métodos de pago que usen ese proveedor
    payment_provider_id = fields.Many2one(
        'payment.provider',
        string='Proveedor de Pago',
        required=True,
        domain=[('state', 'in', ['enabled', 'test'])],
        help='Proveedor de pago en el que aplica esta promoción. '
             'Se aplicará en todos los métodos de pago (POS y web) que usen este proveedor.'
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
    
    # Promociones estándar de Odoo (Descuento y lealtad) incompatibles con esta promoción
    incompatible_promotion_ids = fields.Many2many(
        'loyalty.program',
        'payment_method_promotion_loyalty_incompatible_rel',
        'promotion_id',
        'loyalty_program_id',
        string='Promociones Incompatibles',
        help='Programas de lealtad aplicados en el pedido que no pueden combinarse con esta '
             'promoción de tarjeta. Si el carrito tiene uno de estos programas activo (y vigente), '
             'el cobro OCA con promo se cancela y se solicita reversa.'
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
    
    @api.constrains('payment_provider_id')
    def _check_payment_config(self):
        """
        Valida que se configure el proveedor de pago (aplica a todos los métodos con ese proveedor)
        """
        for record in self:
            if not record.payment_provider_id:
                raise ValidationError(_('Debe configurar el Proveedor de Pago'))
    
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
        Verifica si la promoción aplica para el proveedor de pago dado.
        La promoción se configura solo por proveedor; aplica a todos los métodos con ese proveedor.
        
        Args:
            provider_code (str): Código del proveedor de pago (ej: 'oca', 'stripe')
            payment_method_id (int): No usado; se mantiene por compatibilidad de firma
            
        Returns:
            bool: True si el proveedor coincide, False en caso contrario
        """
        self.ensure_one()
        if provider_code and self.payment_provider_id:
            return self.payment_provider_id.code == provider_code
        return False
    
    def _loyalty_program_rules_active(self, program):
        """
        True si el loyalty.program sigue activo/vigente a nivel de sistema (active y fechas),
        para decidir si una incompatibilidad configurada sigue 'en vigor'.
        """
        self.ensure_one()
        if not program:
            return False
        if hasattr(program, 'active') and not program.active:
            return False
        today = date.today()
        date_from = getattr(program, 'date_from', None)
        date_to = getattr(program, 'date_to', None)
        if date_from and today < date_from:
            return False
        if date_to and today > date_to:
            return False
        return True

    @api.model
    def collect_applied_loyalty_program_ids_from_pos_order(self, order):
        """
        Devuelve los IDs de loyalty.program presentes en líneas del pedido POS (recompensas/cupones).

        Se usa cuando el borrador ya existe en el servidor; se combina con el snapshot en pos.session.
        """
        ids = []
        if not order or not hasattr(order, "lines"):
            _logger.info(
                "OCA_PROMOS_ORDER_LINES: sin order o sin lines | order=%s",
                order.id if order else None,
            )
            return ids
        seen = set()
        for line in order.lines:
            reward = getattr(line, "reward_id", None)
            if reward:
                prog = getattr(reward, "program_id", None)
                if prog and prog.id and prog.id not in seen:
                    seen.add(prog.id)
                    ids.append(prog.id)
            coupon = getattr(line, "coupon_id", None)
            if coupon:
                prog = getattr(coupon, "program_id", None)
                if prog and prog.id and prog.id not in seen:
                    seen.add(prog.id)
                    ids.append(prog.id)
        _logger.info(
            "OCA_PROMOS_ORDER_LINES: pos.order id=%s | líneas=%s | loyalty.program ids=%s",
            order.id,
            len(order.lines),
            ids,
        )
        return ids

    def get_incompatibility_payment_block_for_applied_programs(self, applied_program_ids):
        """
        Bloquea el cobro con promo OCA si el pedido/carrito tiene aplicado algún loyalty.program
        que figure en incompatible_promotion_ids y siga activo/vigente en Odoo.

        Args:
            applied_program_ids (list|tuple|set|False): IDs de loyalty.program aplicados en el carrito.

        Returns:
            tuple: (blocked: bool, message: str)
        """
        self.ensure_one()
        if not applied_program_ids:
            _logger.info(
                "OCA_PROMOS_INCOMPAT: promo_id=%s | sin IDs de lealtad aplicados en carrito → NO bloqueo",
                self.id,
            )
            return False, ""
        try:
            id_set = {
                int(x)
                for x in applied_program_ids
                if x is not None and str(x).strip() != ""
            }
        except (TypeError, ValueError) as err:
            _logger.warning(
                "OCA_PROMOS_INCOMPAT: error normalizando applied_program_ids | promo_id=%s | err=%s",
                self.id,
                err,
            )
            return False, ""
        if not id_set:
            return False, ""
        applied = self.env["loyalty.program"].browse(list(id_set)).exists()
        _logger.info(
            "OCA_PROMOS_INCOMPAT: promo_id=%s | name=%s | aplicados_en_carrito_ids=%s | "
            "aplicados_existentes=%s | incompatible_promotion_ids(config)=%s",
            self.id,
            self.name,
            sorted(id_set),
            applied.ids,
            self.incompatible_promotion_ids.ids,
        )
        conflicting = self.env["loyalty.program"]
        for prog in applied:
            in_list = prog in self.incompatible_promotion_ids
            if not in_list:
                _logger.info(
                    "OCA_PROMOS_INCOMPAT: eval programa id=%s name=%r | en_incompatibles=False",
                    prog.id,
                    prog.name,
                )
                continue
            rules_ok = self._loyalty_program_rules_active(prog)
            _logger.info(
                "OCA_PROMOS_INCOMPAT: eval programa id=%s name=%r | en_incompatibles=True | "
                "reglas_activas/vigentes=%s",
                prog.id,
                prog.name,
                rules_ok,
            )
            if rules_ok:
                conflicting |= prog
        if not conflicting:
            _logger.info(
                "OCA_PROMOS_INCOMPAT: promo_id=%s | sin cruce incompatible activo → NO bloqueo",
                self.id,
            )
            return False, ""
        names = ", ".join(conflicting.mapped("name"))
        msg = _(
            'No se puede cobrar con la promoción de tarjeta "%(promo)s": en el pedido hay aplicado '
            'el programa de beneficios "%(programs)s", incompatible con esta promoción. '
            "Quite ese beneficio o utilice otro medio de pago."
        ) % {"promo": self.name, "programs": names}
        _logger.warning(
            "OCA_PROMOS_INCOMPAT: BLOQUEO | promo_id=%s | programas_conflictivos=%s | msg=%s",
            self.id,
            conflicting.ids,
            msg,
        )
        return True, msg

    @api.model
    def find_applicable_promotion(self, card_data, provider_code=None, payment_method_id=None, order=None):
        """
        Busca una promoción aplicable según los criterios dados
        
        Evalúa promociones activas y retorna la primera que cumpla proveedor, BIN y fechas.
        El bloqueo por incompatibilidades activas en sistema no se aplica aquí.
        
        Args:
            card_data (dict): Datos de la tarjeta con keys:
                - Acquirer: Adquirente
                - Issuer: Emisor
                - CardNumber: Número de tarjeta o BIN
            provider_code (str): Código del proveedor de pago
            payment_method_id (int): ID del método de pago POS
            order: Obsoleto, se ignora. La incompatibilidad se evalúa con los programas aplicados
                en carrito (pos.session + pos.order borrador) vía
                ``get_incompatibility_payment_block_for_applied_programs()``.
            
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
            
            # Coincide por tarjeta; el bloqueo por lealtad aplicada en carrito se hace después.
            
            # Promoción candidata por BIN/proveedor/fechas
            _logger.info('Promoción aplicable encontrada: %s (ID: %s)', promotion.name, promotion.id)
            return promotion
        
        return None
    
    def action_increment_times_applied(self):
        """
        Incrementa el contador de veces aplicada
        """
        self.ensure_one()
        self.times_applied += 1
