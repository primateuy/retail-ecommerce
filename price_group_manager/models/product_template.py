from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class ProductTemplate(models.Model):
    """
    Herencia del modelo product.template
    Agrega campos y métodos para manejar agrupadores de precio con vigencia
    """
    _inherit = 'product.template'

    # Campos de agrupadores de precio
    x_price_group_line_ids = fields.One2many(
        'x_price_group_line',
        'product_tmpl_id',
        string='Líneas de Agrupador de Precio',
        help='Agrupadores de precio asignados a este producto template'
    )
    
    x_price_group_ids = fields.Many2many(
        'x_price_group',
        string='Agrupadores de Precio',
        compute='_compute_price_groups',
        store=True,
        help='Agrupadores de precio vigentes actualmente para este producto'
    )
    
    x_current_price_group_id = fields.Many2one(
        'x_price_group',
        string='Agrupador de Precio Vigente',
        compute='_compute_current_price_group',
        store=True,
        help='Agrupador de precio vigente en la fecha actual'
    )
    
    x_price_group_count = fields.Integer(
        string='Cantidad de Agrupadores',
        compute='_compute_price_group_count',
        help='Cantidad total de agrupadores de precio asignados'
    )

    @api.depends('x_price_group_line_ids', 'x_price_group_line_ids.active', 
                'x_price_group_line_ids.date_start', 'x_price_group_line_ids.date_end')
    def _compute_price_groups(self):
        """
        Calcula los agrupadores de precio vigentes para este producto template.
        """
        today = date.today()
        for record in self:
            # Obtener líneas vigentes
            current_lines = record.x_price_group_line_ids.filtered(
                lambda l: l.active and l.is_current
            )
            
            # Obtener agrupadores únicos
            price_groups = current_lines.mapped('price_group_id')
            record.x_price_group_ids = [(6, 0, price_groups.ids)]

    @api.depends('x_price_group_line_ids', 'x_price_group_line_ids.active',
                'x_price_group_line_ids.date_start', 'x_price_group_line_ids.date_end')
    def _compute_current_price_group(self):
        """
        Calcula el agrupador de precio vigente en la fecha actual.
        Si hay múltiples, toma el primero por orden de prioridad.
        """
        today = date.today()
        for record in self:
            record.x_price_group_line_ids._compute_is_current()
            # Obtener líneas vigentes ordenadas por prioridad
            current_lines = record.x_price_group_line_ids.filtered(
                lambda l: l.active and l.is_current
            ).sorted('date_start', reverse=True)
            
            if current_lines:
                record.x_current_price_group_id = current_lines[0].price_group_id
            else:
                record.x_current_price_group_id = False

    @api.depends('x_price_group_line_ids')
    def _compute_price_group_count(self):
        """
        Calcula la cantidad total de agrupadores de precio asignados.
        """
        for record in self:
            record.x_price_group_count = len(record.x_price_group_line_ids)

    def action_view_price_groups(self):
        """
        Acción para ver los agrupadores de precio de este producto.
        """
        self.ensure_one()
        
        return {
            'name': _('Agrupadores de Precio: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'x_price_group_line',
            'view_mode': 'tree,form',
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {
                'default_product_tmpl_id': self.id,
                'default_origin': 'template'
            },
        }

    def action_force_price_group_sync(self):
        """
        Fuerza la sincronización del agrupador de precio en todas las variantes.
        Elimina todas las líneas de las variantes y copia la última línea del template.
        """
        self.ensure_one()
        
        # Verificar que haya líneas en el template
        if not self.x_price_group_line_ids:
            raise ValidationError(_(
                'No hay agrupadores de precio configurados en este producto template.'
            ))
        
        # Obtener la última línea activa del template
        last_line = self.x_price_group_line_ids.filtered(
            lambda l: l.active
        ).sorted('date_start', reverse=True)[:1]
        
        if not last_line:
            raise ValidationError(_(
                'No hay agrupadores de precio activos en este producto template.'
            ))
        
        # Eliminar todas las líneas existentes de las variantes
        variant_lines = self.env['x_price_group_line'].search([
            ('product_tmpl_id', '=', self.id),
            ('product_id', '!=', False)
        ])
        variant_lines.unlink()
        
        # Crear nuevas líneas heredadas en todas las variantes
        for variant in self.product_variant_ids:
            self.env['x_price_group_line'].create({
                'product_tmpl_id': self.id,
                'product_id': variant.id,
                'price_group_id': last_line.price_group_id.id,
                'date_start': last_line.date_start,
                'date_end': last_line.date_end,
                'origin': 'inherited',
                'parent_line_id': last_line.id,
            })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sincronización Completada'),
                'message': _('Se sincronizaron %d variantes con el agrupador "%s".') % (
                    len(self.product_variant_ids), last_line.price_group_id.name
                ),
                'type': 'success',
            }
        }

    def action_add_price_group(self):
        """
        Acción para agregar un nuevo agrupador de precio al producto.
        """
        self.ensure_one()
        
        return {
            'name': _('Agregar Agrupador de Precio'),
            'type': 'ir.actions.act_window',
            'res_model': 'x_price_group_line',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_tmpl_id': self.id,
                'default_origin': 'template'
            },
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
        
        # Buscar líneas vigentes para la fecha específica
        valid_lines = self.x_price_group_line_ids.filtered(
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

    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para manejar la creación de productos
        con agrupadores de precio.
        """
        # Crear el producto template
        product = super().create(vals)
        
        # Si se especificaron agrupadores de precio, crearlos
        if 'x_price_group_ids' in vals and vals['x_price_group_ids']:
            self._create_price_group_lines_from_vals(product, vals)
        
        return product

    def write(self, vals):
        """
        Sobrescribe el método write para manejar cambios en agrupadores de precio.
        """
        # Procesar cambios en agrupadores de precio
        if 'x_price_group_ids' in vals:
            self._update_price_group_lines_from_vals(vals)
        
        return super().write(vals)

    def _create_price_group_lines_from_vals(self, product, vals):
        """
        Crea líneas de agrupador de precio desde los valores del create.
        """
        price_group_ids = vals.get('x_price_group_ids', [])
        
        for command in price_group_ids:
            if command[0] == 6:  # replace
                # Eliminar líneas existentes
                product.x_price_group_line_ids.unlink()
                
                # Crear nuevas líneas
                for group_id in command[2]:
                    self.env['x_price_group_line'].create({
                        'product_tmpl_id': product.id,
                        'price_group_id': group_id,
                        'origin': 'template',
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
                        'product_tmpl_id': self.id,
                        'price_group_id': group_id,
                        'origin': 'template',
                    })
                break 