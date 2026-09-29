import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


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
    date_start = fields.Datetime(
        string='Fecha de Inicio',
        help='Fecha desde la cual el agrupador está vigente (vacío = sin límite)'
    )
    
    date_end = fields.Datetime(
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

    @api.onchange('activo')
    def change_activo(self):
        for rec in self:
            if not rec.activo:
                rec.date_end = fields.Datetime().now()

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
        today = fields.Datetime().now()
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

    @api.constrains('date_start', 'date_end', 'price_group_id', 'product_tmpl_id', 'product_id', 'activo')
    def _check_dates(self):
        """
        Valida que las fechas sean coherentes y que no haya dos agrupadores
        vigentes a la vez para el mismo producto.

        Antes sólo miraba las fechas: al crear una línea no corría nunca (las
        fechas no vienen en los valores) y la importación dejaba duplicados.
        """
        for record in self:
            if record.date_start and record.date_end and record.date_start > record.date_end:
                raise ValidationError(_(
                    'La fecha de inicio no puede ser posterior a la fecha de fin.'
                ))
            if record.activo:
                self._check_date_overlap(record)

    def _dominio_mismo_producto(self, product_tmpl_id, product_id):
        """Líneas activas del mismo producto: las de la variante si la línea es
        de variante, o las propias del template (sin variante) si no."""
        domain = [('activo', '=', True)]
        if product_id:
            domain.append(('product_id', '=', product_id))
        else:
            domain += [('product_tmpl_id', '=', product_tmpl_id), ('product_id', '=', False)]
        return domain

    def _check_date_overlap(self, record):
        """
        Verifica que no haya superposición de fechas con otras líneas del mismo
        producto, sea cual sea el agrupador: un producto tiene un solo
        agrupador vigente por vez.
        """
        domain = self._dominio_mismo_producto(record.product_tmpl_id.id, record.product_id.id)
        domain.append(('id', '!=', record.id))
        for line in self.search(domain):
            if self._dates_overlap(record, line):
                raise ValidationError(_(
                    'Existe superposición de fechas con la línea "%s". '
                    'No puede haber dos agrupadores vigentes para el mismo producto '
                    'en las mismas fechas.'
                ) % line.display_name)

    def _dates_overlap(self, line1, line2):
        """
        Determina si dos líneas tienen fechas que se superponen. Sin fecha de
        inicio o de fin, el intervalo queda abierto de ese lado.

        Se usaba date.min/date.max contra campos Datetime: con una sola de las
        dos fechas cargada la comparación reventaba con TypeError.
        """
        start1 = line1.date_start or datetime.min
        end1 = line1.date_end or datetime.max
        start2 = line2.date_start or datetime.min
        end2 = line2.date_end or datetime.max
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

        # now = fields.Datetime().now()
        # if not self.activo:
        #     date_end = now
        #     self.with_context(write_direct=True).write({'date_end': date_end})

        vals = {
            'pricelist_id': self.price_group_id.lista_precio_id.id,
            'date_start': self.date_start,
            'date_end': self.date_end,
            'applied_on': applied_on,
            'compute_price': 'fixed',
            'fixed_price': self.valor_fijo,
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

    def _preparar_vals_producto(self, vals):
        """
        Completa el producto de la línea cuando viene desde la lista del
        template (x_price_group_line_ids del producto, que es lo que usa la
        importación).

        Esa lista tiene como inversa product_tmpl_relacion_id, que es un campo
        calculado: Odoo sólo completa ése y la línea quedaba sin
        product_tmpl_id. La regla de la lista de precios se creaba sin producto
        y Odoo la rechazaba ("Please specify the product for which this rule
        should be applied"): no se podía importar ni un archivo recién exportado.
        """
        if (vals.get('product_tmpl_relacion_id') and not vals.get('product_tmpl_id')
                and not vals.get('product_id') and vals.get('origin', 'template') == 'template'):
            vals['product_tmpl_id'] = vals['product_tmpl_relacion_id']
        return vals

    def _reemplazar_agrupador_vigente(self, vals):
        """
        Aplica la regla de un solo agrupador vigente por producto antes de crear.

        - Si el producto ya tiene ESE agrupador vigente, no se crea nada y se
          devuelve la línea existente: reimportar un archivo no duplica.
        - Si tiene otro, se cierra el anterior justo antes de que empiece el
          nuevo (queda el historial y su regla de precio deja de aplicar). Una
          línea nueva sin fecha de inicio empieza ahora, para no superponerse
          con el historial del producto.

        :return: la línea existente a reutilizar, o una vacía si hay que crear.
        """
        tmpl_id, product_id = vals.get('product_tmpl_id'), vals.get('product_id')
        if not vals.get('activo', True) or not (tmpl_id or product_id) or not vals.get('price_group_id'):
            return self.browse()
        date_start = fields.Datetime.to_datetime(vals.get('date_start'))
        date_end = fields.Datetime.to_datetime(vals.get('date_end'))
        otras = self.search(self._dominio_mismo_producto(tmpl_id, product_id))
        if not otras:
            return self.browse()

        mismo = otras.filtered(lambda l: l.price_group_id.id == vals['price_group_id'])
        if not date_start and not date_end:
            # Sin fechas = "este es el agrupador de ahora": si ya está vigente
            # y sin fin, no hay nada que hacer.
            # No se usa is_current: es almacenado y queda con el "hoy" del día
            # en que se calculó.
            ahora = fields.Datetime.now()
            vigente = mismo.filtered(lambda l: not l.date_end and (not l.date_start or l.date_start <= ahora))
            if vigente:
                return vigente[:1]
        else:
            igual = mismo.filtered(lambda l: l.date_start == date_start and l.date_end == date_end)
            if igual:
                return igual[:1]

        corte = date_start or fields.Datetime.now().replace(microsecond=0)
        if not date_start:
            vals['date_start'] = corte
        fin_nueva = date_end or datetime.max
        for linea in otras:
            inicio = linea.date_start or datetime.min
            fin = linea.date_end or datetime.max
            if fin < corte or inicio > fin_nueva:
                continue  # no se pisan
            if inicio >= corte:
                raise UserError(_(
                    'El producto ya tiene programado el agrupador "%s" a partir del %s. '
                    'Ajuste o elimine esa línea antes de asignar "%s".'
                ) % (linea.price_group_id.name, linea.date_start,
                     self.env['x_price_group'].browse(vals['price_group_id']).name))
            linea.write({'date_end': corte - timedelta(seconds=1)})
            _logger.info('Agrupador de precio: se cierra la línea %s (%s) al asignar otro agrupador.',
                         linea.id, linea.price_group_id.name)
        return self.browse()

    @api.model_create_multi
    def create(self, vals_list):
        # Una por una: dos filas del mismo producto en una misma importación
        # tienen que verse entre sí para el reemplazo.
        lineas = self.browse()
        for vals in vals_list:
            vals = self._preparar_vals_producto(dict(vals))
            existente = self._reemplazar_agrupador_vigente(vals)
            if existente:
                # Concatenado (no unión): una posición por cada vals, como espera
                # la importación.
                lineas += existente
                continue
            new_id = super(PriceGroupLine, self).create([vals])
            if not new_id.price_group_id.lista_precio_id:
                raise UserError(f'El agrupador {new_id.price_group_id.name} no tiene lista de precio configurada')
            new_id.actualizar_lista_precio_item()
            lineas += new_id
        return lineas

    def write(self, vals):
        res = super(PriceGroupLine, self).write(vals)

        if self._context.get('write_direct', False):
            return res

        for rec in self:
            rec.actualizar_lista_precio_item()

        return res

    def unlink(self):
        price_list_item_ids = self.mapped('price_list_item_id')
        res = super(PriceGroupLine, self).unlink()
        price_list_item_ids.sudo().unlink()
        return res
