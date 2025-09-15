from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class ProductProduct(models.Model):
    """
    Herencia del modelo product.product
    Agrega campos y métodos para manejar agrupadores de precio con vigencia en variantes
    """
    _inherit = 'product.product'

    # Campos de agrupadores de precio
    x_price_group_line_ids = fields.One2many(
        'x_price_group_line',
        'product_id',
        string='Líneas de Agrupador de Precio',
        help='Agrupadores de precio asignados específicamente a esta variante'
    )
    
    x_price_group_ids = fields.Many2many(
        'x_price_group',
        string='Agrupadores de Precio',
        compute='_compute_price_groups',
        store=True,
        help='Agrupadores de precio vigentes actualmente para esta variante'
    )
    
    x_current_price_group_id = fields.Many2one(
        'x_price_group',
        string='Agrupador de Precio Vigente',
        compute='_compute_current_price_group',
        store=True,
        help='Agrupador de precio vigente en la fecha actual para esta variante'
    )
    
    x_price_group_count = fields.Integer(
        string='Cantidad de Agrupadores',
        compute='_compute_price_group_count',
        help='Cantidad total de agrupadores de precio asignados a esta variante'
    )
    
    x_inherited_price_group_id = fields.Many2one(
        'x_price_group',
        string='Agrupador Heredado del Template',
        compute='_compute_inherited_price_group',
        store=True,
        help='Agrupador de precio heredado del template (si no tiene líneas propias)'
    )

    @api.depends('x_price_group_line_ids', 'x_price_group_line_ids.active',
                'x_price_group_line_ids.date_start', 'x_price_group_line_ids.date_end',
                'product_tmpl_id.x_price_group_line_ids', 'product_tmpl_id.x_price_group_line_ids.active',
                'product_tmpl_id.x_price_group_line_ids.date_start', 'product_tmpl_id.x_price_group_line_ids.date_end')
    def _compute_price_groups(self):
        """
        Calcula los agrupadores de precio vigentes para esta variante.
        Si la variante no tiene líneas propias, hereda del template.
        """
        today = date.today()
        for record in self:
            # Primero verificar si la variante tiene líneas propias
            if record.x_price_group_line_ids:
                # Usar líneas propias de la variante
                current_lines = record.x_price_group_line_ids.filtered(
                    lambda l: l.active and l.is_current
                )
            else:
                # Heredar del template
                current_lines = record.product_tmpl_id.x_price_group_line_ids.filtered(
                    lambda l: l.active and l.is_current
                )
            
            # Obtener agrupadores únicos
            price_groups = current_lines.mapped('price_group_id')
            record.x_price_group_ids = [(6, 0, price_groups.ids)]

    @api.depends('x_price_group_line_ids', 'x_price_group_line_ids.active',
                'x_price_group_line_ids.date_start', 'x_price_group_line_ids.date_end',
                'product_tmpl_id.x_price_group_line_ids', 'product_tmpl_id.x_price_group_line_ids.active',
                'product_tmpl_id.x_price_group_line_ids.date_start', 'product_tmpl_id.x_price_group_line_ids.date_end')
    def _compute_current_price_group(self):
        """
        Calcula el agrupador de precio vigente en la fecha actual para esta variante.
        Si hay múltiples, toma el primero por orden de prioridad.
        """
        today = date.today()
        for record in self:
            # Primero verificar si la variante tiene líneas propias
            if record.x_price_group_line_ids:
                # Usar líneas propias de la variante
                record.x_price_group_line_ids._compute_is_current()
                current_lines = record.x_price_group_line_ids.filtered(
                    lambda l: l.active and l.is_current
                ).sorted('date_start', reverse=True)
            else:
                # Heredar del template
                record.product_tmpl_id.x_price_group_line_ids._compute_is_current()
                current_lines = record.product_tmpl_id.x_price_group_line_ids.filtered(
                    lambda l: l.active and l.is_current
                ).sorted('date_start', reverse=True)
            
            if current_lines:
                record.x_current_price_group_id = current_lines[0].price_group_id
            else:
                record.x_current_price_group_id = False

    @api.depends('x_price_group_line_ids')
    def _compute_price_group_count(self):
        """
        Calcula la cantidad total de agrupadores de precio asignados a esta variante.
        """
        for record in self:
            record.x_price_group_count = len(record.x_price_group_line_ids)

    @api.depends('x_price_group_line_ids', 'product_tmpl_id.x_price_group_line_ids')
    def _compute_inherited_price_group(self):
        """
        Calcula el agrupador de precio heredado del template.
        Solo se aplica si la variante no tiene líneas propias.
        """
        today = date.today()
        for record in self:
            if record.x_price_group_line_ids:
                # Si tiene líneas propias, no hereda
                record.x_inherited_price_group_id = False
            else:
                # Heredar del template
                current_lines = record.product_tmpl_id.x_price_group_line_ids.filtered(
                    lambda l: l.active and l.is_current
                ).sorted('date_start', reverse=True)
                
                if current_lines:
                    record.x_inherited_price_group_id = current_lines[0].price_group_id
                else:
                    record.x_inherited_price_group_id = False

    def action_view_price_groups(self):
        """
        Acción para ver los agrupadores de precio de esta variante.
        """
        self.ensure_one()
        
        return {
            'name': _('Agrupadores de Precio: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'x_price_group_line',
            'view_mode': 'tree,form',
            'domain': [('product_id', '=', self.id)],
            'context': {
                'default_product_tmpl_id': self.product_tmpl_id.id,
                'default_product_id': self.id,
                'default_origin': 'variant'
            },
        }

    def action_add_price_group(self):
        """
        Acción para agregar un nuevo agrupador de precio a esta variante.
        """
        self.ensure_one()
        
        return {
            'name': _('Agregar Agrupador de Precio'),
            'type': 'ir.actions.act_window',
            'res_model': 'x_price_group_line',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_tmpl_id': self.product_tmpl_id.id,
                'default_product_id': self.id,
                'default_origin': 'variant'
            },
        }

    def action_inherit_from_template(self):
        """
        Hereda el agrupador de precio del template a esta variante.
        Solo funciona si la variante no tiene líneas propias.
        """
        self.ensure_one()
        
        if self.x_price_group_line_ids:
            raise ValidationError(_(
                'Esta variante ya tiene agrupadores de precio propios. '
                'No puede heredar del template.'
            ))
        
        # Obtener la línea vigente del template
        template_line = self.product_tmpl_id.x_price_group_line_ids.filtered(
            lambda l: l.active and l.is_current
        )[:1]
        
        if not template_line:
            raise ValidationError(_(
                'El template no tiene agrupadores de precio vigentes para heredar.'
            ))
        
        # Crear línea heredada
        self.env['x_price_group_line'].create({
            'product_tmpl_id': self.product_tmpl_id.id,
            'product_id': self.id,
            'price_group_id': template_line.price_group_id.id,
            'date_start': template_line.date_start,
            'date_end': template_line.date_end,
            'origin': 'inherited',
            'parent_line_id': template_line.id,
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Herencia Completada'),
                'message': _('Se heredó el agrupador "%s" del template.') % template_line.price_group_id.name,
                'type': 'success',
            }
        }

    def get_price_group_for_date(self, target_date=None):
        """
        Obtiene el agrupador de precio vigente para una fecha específica.
        
        Args:
            target_date (date): Fecha para la cual obtener el agrupador.
                              Si es None, usa la fecha actual.
        
        Returns:
            x_price_group: Agrupador de precio vigente o False si no hay ninguno
        """
        if target_date is None:
            target_date = date.today()
        
        # Primero verificar si la variante tiene líneas propias
        if self.x_price_group_line_ids:
            # Usar líneas propias de la variante
            valid_lines = self.x_price_group_line_ids.filtered(
                lambda l: l.active and self._is_line_valid_for_date(l, target_date)
            )
        else:
            # Heredar del template
            valid_lines = self.product_tmpl_id.x_price_group_line_ids.filtered(
                lambda l: l.active and self._is_line_valid_for_date(l, target_date)
            )
        
        if valid_lines:
            # Retornar el primero por orden de prioridad
            return valid_lines.sorted('date_start', reverse=True)[0].price_group_id
        
        return False

    def _is_line_valid_for_date(self, line, target_date):
        """
        Verifica si una línea de agrupador es válida para una fecha específica.
        
        Args:
            line (x_price_group_line): Línea a validar
            target_date (date): Fecha para validar
        
        Returns:
            bool: True si la línea es válida para la fecha
        """
        # Si no hay fechas, está vigente
        if not line.date_start and not line.date_end:
            return True
        
        # Validar fecha de inicio
        if line.date_start and target_date < line.date_start:
            return False
        
        # Validar fecha de fin
        if line.date_end and target_date > line.date_end:
            return False
        
        return True

    def has_own_price_groups(self):
        """
        Verifica si la variante tiene agrupadores de precio propios.
        
        Returns:
            bool: True si la variante tiene líneas propias
        """
        return bool(self.x_price_group_line_ids)

    def is_inheriting_from_template(self):
        """
        Verifica si la variante está heredando agrupadores del template.
        
        Returns:
            bool: True si la variante hereda del template
        """
        return not self.has_own_price_groups() and bool(self.x_inherited_price_group_id)

    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para manejar la creación de variantes
        con agrupadores de precio.
        """
        # Crear la variante
        variant = super().create(vals)
        
        # Si se especificaron agrupadores de precio, crearlos
        if 'x_price_group_ids' in vals and vals['x_price_group_ids']:
            self._create_price_group_lines_from_vals(variant, vals)
        
        return variant

    def write(self, vals):
        """
        Sobrescribe el método write para manejar cambios en agrupadores de precio.
        """
        # Procesar cambios en agrupadores de precio
        if 'x_price_group_ids' in vals:
            self._update_price_group_lines_from_vals(vals)
        
        return super().write(vals)

    def _create_price_group_lines_from_vals(self, variant, vals):
        """
        Crea líneas de agrupador de precio desde los valores del create.
        """
        price_group_ids = vals.get('x_price_group_ids', [])
        
        for command in price_group_ids:
            if command[0] == 6:  # replace
                # Eliminar líneas existentes
                variant.x_price_group_line_ids.unlink()
                
                # Crear nuevas líneas
                for group_id in command[2]:
                    self.env['x_price_group_line'].create({
                        'product_tmpl_id': variant.product_tmpl_id.id,
                        'product_id': variant.id,
                        'price_group_id': group_id,
                        'origin': 'variant',
                    })
                break

    def _update_price_group_lines_from_vals(self, vals):
        """
        Actualiza líneas de agrupador de precio desde los valores del write.
        """
        price_group_ids = vals.get('x_price_group_ids', [])
        
        for command in price_group_ids:
            if command[0] == 6:  # replace
                # Eliminar líneas existentes
                self.x_price_group_line_ids.unlink()
                
                # Crear nuevas líneas
                for group_id in command[2]:
                    self.env['x_price_group_line'].create({
                        'product_tmpl_id': self.product_tmpl_id.id,
                        'product_id': self.id,
                        'price_group_id': group_id,
                        'origin': 'variant',
                    })
                break 