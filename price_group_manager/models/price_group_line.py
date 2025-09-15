from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class PriceGroupLine(models.Model):
    """
    Línea de Agrupador de Precio por Producto
    Establece la relación entre un producto y un agrupador de precio
    con fechas de vigencia específicas.
    """
    _name = 'x_price_group_line'
    _description = 'Línea de Agrupador de Precio'
    _order = 'date_start desc, date_end desc'
    _rec_name = 'display_name'

    # Campos de identificación
    name = fields.Char(
        string='Descripción',
        compute='_compute_name',
        store=True,
        help='Descripción automática de la línea'
    )
    
    display_name = fields.Char(
        string='Nombre para Mostrar',
        compute='_compute_display_name',
        store=True,
        help='Nombre formateado para mostrar en vistas'
    )
    
    # Campos de relación
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Producto Template',
        required=True,
        ondelete='cascade',
        help='Producto template al que se asigna el agrupador'
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Variante de Producto',
        ondelete='cascade',
        help='Variante específica del producto (opcional)'
    )
    
    price_group_id = fields.Many2one(
        'x_price_group',
        string='Agrupador de Precio',
        required=True,
        ondelete='restrict',
        help='Agrupador de precio asignado al producto'
    )
    
    # Campos de vigencia
    date_start = fields.Date(
        string='Fecha de Inicio',
        help='Fecha desde la cual el agrupador está vigente (vacío = sin límite)'
    )
    
    date_end = fields.Date(
        string='Fecha de Fin',
        help='Fecha hasta la cual el agrupador está vigente (vacío = sin límite)'
    )
    
    # Campos de control
    active = fields.Boolean(
        string='Activo',
        default=True,
        help='Indica si la línea está activa'
    )
    
    origin = fields.Selection([
        ('template', 'Template'),
        ('variant', 'Variante'),
        ('inherited', 'Heredado')
    ], string='Origen', default='template', required=True,
       help='Indica el origen de la línea de agrupador')
    
    is_inherited = fields.Boolean(
        string='Es Heredado',
        compute='_compute_is_inherited',
        store=True,
        help='Indica si la línea fue heredada del template'
    )
    
    is_current = fields.Boolean(
        string='Vigente Hoy',
        compute='_compute_is_current',
        store=True,
        help='Indica si el agrupador está vigente en la fecha actual'
    )
    
    # Campos de trazabilidad
    parent_line_id = fields.Many2one(
        'x_price_group_line',
        string='Línea Padre',
        help='Línea del template desde la cual se heredó (si aplica)'
    )
    
    child_line_ids = fields.One2many(
        'x_price_group_line',
        'parent_line_id',
        string='Líneas Hijas',
        help='Líneas de variantes que heredan de esta línea'
    )

    # Constraints de base de datos
    _sql_constraints = [
        ('unique_product_template_group_date', 
         'UNIQUE(product_tmpl_id, product_id, price_group_id, date_start, date_end)',
         'No puede haber líneas duplicadas para el mismo template, agrupador y fechas.')
    ]

    @api.depends('product_tmpl_id', 'product_id', 'price_group_id', 'date_start', 'date_end')
    def _compute_name(self):
        """
        Genera una descripción automática de la línea basada en sus campos.
        """
        for record in self:
            product_name = record.product_id.name or record.product_tmpl_id.name
            group_name = record.price_group_id.name
            dates = []
            
            if record.date_start:
                dates.append(f"Desde: {record.date_start}")
            if record.date_end:
                dates.append(f"Hasta: {record.date_end}")
            
            date_str = " - ".join(dates) if dates else "Vigencia ilimitada"
            record.name = f"{product_name} - {group_name} ({date_str})"

    @api.depends('product_tmpl_id', 'product_id', 'price_group_id', 'date_start', 'date_end', 'origin')
    def _compute_display_name(self):
        """
        Genera un nombre formateado para mostrar en vistas.
        """
        for record in self:
            product_name = record.product_id.name or record.product_tmpl_id.name
            group_name = record.price_group_id.name
            origin_str = f"[{record.origin.upper()}]" if record.origin != 'template' else ""
            
            if record.date_start and record.date_end:
                date_str = f"{record.date_start} - {record.date_end}"
            elif record.date_start:
                date_str = f"Desde {record.date_start}"
            elif record.date_end:
                date_str = f"Hasta {record.date_end}"
            else:
                date_str = "Vigencia ilimitada"
            
            record.display_name = f"{product_name} - {group_name} ({date_str}) {origin_str}"

    @api.depends('parent_line_id')
    def _compute_is_inherited(self):
        """
        Determina si la línea fue heredada del template.
        """
        for record in self:
            record.is_inherited = bool(record.parent_line_id)

    @api.depends('date_start', 'date_end', 'active')
    def _compute_is_current(self):
        """
        Determina si el agrupador está vigente en la fecha actual.
        """
        today = date.today()
        for record in self:
            if not record.active:
                record.is_current = False
                continue
            
            # Si no hay fechas, está vigente
            if not record.date_start and not record.date_end:
                record.is_current = True
                continue
            
            # Validar fecha de inicio
            if record.date_start and today < record.date_start:
                record.is_current = False
                continue
            
            # Validar fecha de fin
            if record.date_end and today > record.date_end:
                record.is_current = False
                continue
            
            record.is_current = True

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """
        Valida que las fechas sean coherentes y no haya superposición.
        """
        for record in self:
            # Validar que fecha de inicio no sea posterior a fecha de fin
            if record.date_start and record.date_end and record.date_start > record.date_end:
                raise ValidationError(_(
                    'La fecha de inicio no puede ser posterior a la fecha de fin.'
                ))
            
            # Validar que no haya superposición con otras líneas del mismo producto
            self._check_date_overlap(record)

    def _check_date_overlap(self, record):
        """
        Verifica que no haya superposición de fechas con otras líneas del mismo producto.
        """
        domain = [
            ('id', '!=', record.id),
            ('active', '=', True),
            ('price_group_id', '=', record.price_group_id.id)
        ]
        
        # Determinar el producto a validar
        if record.product_id:
            domain.append(('product_id', '=', record.product_id.id))
        else:
            domain.append(('product_tmpl_id', '=', record.product_tmpl_id.id))
            domain.append(('product_id', '=', False))
        
        # Buscar líneas que puedan superponerse
        overlapping_lines = self.search(domain)
        
        for line in overlapping_lines:
            if self._dates_overlap(record, line):
                raise ValidationError(_(
                    'Existe superposición de fechas con la línea "%s". '
                    'No puede haber dos agrupadores vigentes para el mismo producto '
                    'en las mismas fechas.'
                ) % line.display_name)

    def _dates_overlap(self, line1, line2):
        """
        Determina si dos líneas tienen fechas que se superponen.
        """
        # Si ambas líneas no tienen fechas, se superponen
        if not line1.date_start and not line1.date_end and not line2.date_start and not line2.date_end:
            return True
        
        # Si una línea no tiene fechas, se superpone con cualquier otra
        if not line1.date_start and not line1.date_end:
            return True
        if not line2.date_start and not line2.date_end:
            return True
        
        # Validar superposición con fechas específicas
        start1 = line1.date_start or date.min
        end1 = line1.date_end or date.max
        start2 = line2.date_start or date.min
        end2 = line2.date_end or date.max
        
        return start1 <= end2 and start2 <= end1

    @api.constrains('product_tmpl_id', 'product_id')
    def _check_product_consistency(self):
        """
        Valida que la relación entre template y variante sea consistente.
        """
        for record in self:
            if record.product_id and record.product_tmpl_id:
                if record.product_id.product_tmpl_id.id != record.product_tmpl_id.id:
                    raise ValidationError(_(
                        'La variante seleccionada no pertenece al template especificado.'
                    ))

    def action_inherit_to_variants(self):
        """
        Hereda esta línea del template a todas las variantes que no tengan líneas propias.
        """
        self.ensure_one()
        
        if not self.product_tmpl_id or self.product_id:
            raise ValidationError(_(
                'Solo se pueden heredar líneas de template a variantes.'
            ))
        
        # Obtener variantes sin líneas propias
        variants = self.product_tmpl_id.product_variant_ids.filtered(
            lambda v: not v.x_price_group_line_ids
        )
        
        # Crear líneas heredadas
        for variant in variants:
            self.env['x_price_group_line'].create({
                'product_tmpl_id': self.product_tmpl_id.id,
                'product_id': variant.id,
                'price_group_id': self.price_group_id.id,
                'date_start': self.date_start,
                'date_end': self.date_end,
                'origin': 'inherited',
                'parent_line_id': self.id,
            })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Herencia Completada'),
                'message': _('Se heredaron %d variantes del template.') % len(variants),
                'type': 'success',
            }
        } 