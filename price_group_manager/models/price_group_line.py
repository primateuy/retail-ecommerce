from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date


class PriceGroupLine(models.Model):
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

    origin = fields.Selection([
        ('template', 'Template'),
        ('variant', 'Variante'),
    ], string='Origen', default='template', required=True)

    product_tmpl_relacion_id = fields.Many2one('product.template', compute='compute_product_tmpl_relacion_id', store=True)
    product_tmpl_id = fields.Many2one('product.template', 'Producto Template', ondelete='restrict')
    product_id = fields.Many2one('product.product', 'Variante de Producto', ondelete='restrict')
    product_id_domain = fields.Binary(compute='compute_product_id_domain')

    force_product_tmpl_id = fields.Many2one('product.template', 'Forzar product template', ondelete='set null')
    
    price_group_id = fields.Many2one(
        'x_price_group',
        string='Agrupador de Precio',
        required=True,
        ondelete='restrict',
        help='Agrupador de precio asignado al producto'
    )
    lista_precio_id = fields.Many2one(related='price_group_id.lista_precio_id', store=False, readonly=True)
    valor_fijo = fields.Float(related='price_group_id.valor_fijo', store=False, readonly=True)
    price_list_item_id = fields.Many2one('product.pricelist.item', 'Item lista de precio')

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
    activo = fields.Boolean(
        string='Activo',
        default=True,
        help='Indica si la línea está activa'
    )
    
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

    @api.depends('force_product_tmpl_id', 'origin')
    def compute_product_id_domain(self):
        for rec in self:
            domain = [('active', '=', True)]
            if rec.force_product_tmpl_id:
                variantes_ids = rec.force_product_tmpl_id.product_variant_ids
                domain += [('id', 'in', variantes_ids.ids)]

            rec.product_id_domain = domain

    @api.depends('product_tmpl_id', 'product_id')
    def compute_product_tmpl_relacion_id(self):
        for rec in self:
            template_id = False
            if rec.origin == 'template' and rec.product_tmpl_id:
                template_id = rec.product_tmpl_id
            if rec.origin == 'variant' and rec.product_id:
                template_id = rec.product_id.product_tmpl_id
            rec.product_tmpl_relacion_id = template_id

    @api.onchange('origin')
    def change_origin_clear_productos(self):
        for rec in self:
            rec.product_tmpl_id = False
            rec.product_id = False

            if rec.origin == 'template' and rec.force_product_tmpl_id:
                rec.product_tmpl_id = rec.force_product_tmpl_id

    @api.onchange('price_group_id')
    def change_price_group_id(self):
        for rec in self:
            if rec.price_group_id and rec.price_group_id.lista_precio_id:
                rec.valor_fijo = rec.price_group_id.valor_fijo

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

    @api.depends('date_start', 'date_end', 'activo')
    def _compute_is_current(self):
        """
        Determina si el agrupador está vigente en la fecha actual.
        """
        today = date.today()
        for record in self:
            if not record.activo:
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
            ('activo', '=', True),
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

    def actualizar_lista_precio_item(self):
        self.ensure_one()
        if not self.price_group_id:
            raise UserError('No se encontró agrupador de precio')

        if not self.price_group_id.lista_precio_id:
            raise UserError('No se encontró lista de precio en el agrupador')

        usar_template = True if not self.product_id else False
        applied_on = '1_product' if usar_template else '0_product_variant'

        vals = {
            'pricelist_id': self.price_group_id.lista_precio_id.id,
            'date_start': self.date_start,
            'date_end': self.date_end,
            'applied_on': applied_on,
            'compute_price': 'fixed',
            'fixed_price': self.valor_fijo,
            'min_quantity': 0 if self.activo else 9999999999,
        }

        if usar_template:
            vals.update({
                'product_tmpl_id': self.product_tmpl_id.id
            })
        else:
            vals.update({
                'product_id': self.product_id.id
            })

        if not self.price_list_item_id:
            p_id = self.env['product.pricelist.item'].create([vals])
            self.write({'price_list_item_id': p_id.id})
        else:
            self.price_list_item_id.write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        new_ids = super(PriceGroupLine, self).create(vals_list)

        for new_id in new_ids:
            if not new_id.price_group_id.lista_precio_id:
                raise UserError(f'El agrupador {new_id.price_group_id.name} no tiene lista de precio configurada')
            new_id.actualizar_lista_precio_item()

        return new_ids

    def write(self, vals):
        res = super(PriceGroupLine, self).write(vals)
        for rec in self:
            rec.actualizar_lista_precio_item()
        return res

    def unlink(self):
        price_list_item_ids = self.mapped('price_list_item_id')
        res = super(PriceGroupLine, self).unlink()
        price_list_item_ids.sudo().unlink()
        return res
