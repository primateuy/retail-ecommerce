from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PriceGroup(models.Model):
    """
    Agrupador de Precio
    Permite clasificar productos con fines promocionales o de pricing
    sin depender de la categoría estándar de Odoo.
    """
    _name = 'x_price_group'
    _description = 'Agrupador de Precio'
    _inherit = 'mail.thread'

    # Campos básicos
    name = fields.Char(
        string='Nombre del Agrupador',
        required=True,
        help='Nombre descriptivo del agrupador de precio'
    )
    
    code = fields.Char(
        string='Código',
        size=10,
        help='Código interno opcional para identificación rápida'
    )
    
    active = fields.Boolean(
        string='Activo',
        default=True,
        help='Indica si el agrupador está activo y disponible para uso'
    )

    lista_precio_id = fields.Many2one('product.pricelist', 'Lista de Precio')
    valor_fijo = fields.Float('Valor fijo', digits='Product Price')

    # Campos de relación
    price_group_line_ids = fields.One2many(
        'x_price_group_line',
        'price_group_id',
        string='Líneas de Producto',
        help='Productos asociados a este agrupador'
    )
    
    # Campos calculados
    product_count = fields.Integer(
        string='Cantidad de Productos',
        compute='_compute_product_count',
        help='Cantidad total de productos asociados a este agrupador'
    )
    
    active_product_count = fields.Integer(
        string='Productos Activos',
        compute='_compute_product_count',
        help='Cantidad de productos activos asociados a este agrupador'
    )

    # Constraints de base de datos
    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 
         'El código del agrupador debe ser único.'),
        ('unique_name', 'UNIQUE(name)', 
         'El nombre del agrupador debe ser único.')
    ]

    @api.depends('price_group_line_ids', 'price_group_line_ids.activo')
    def _compute_product_count(self):
        """
        Calcula la cantidad total de productos y productos activos
        asociados a este agrupador.
        """
        for record in self:
            # Cuenta total de productos
            record.product_count = len(record.price_group_line_ids)
            
            # Cuenta productos activos
            active_lines = record.price_group_line_ids.filtered(lambda l: l.activo)
            record.active_product_count = len(active_lines)

    @api.constrains('name')
    def _check_name(self):
        """
        Valida que el nombre del agrupador no esté vacío y tenga longitud mínima.
        """
        for record in self:
            if not record.name or len(record.name.strip()) < 2:
                raise ValidationError(_(
                    'El nombre del agrupador debe tener al menos 2 caracteres.'
                ))

    def action_view_products(self):
        """
        Acción para ver los productos asociados a este agrupador.
        Retorna una vista de lista de productos filtrada por el agrupador.
        """
        self.ensure_one()
        
        # Obtener los productos únicos asociados
        products = self.price_group_line_ids.mapped('product_tmpl_id')
        
        return {
            'name': _('Productos del Agrupador: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', products.ids)],
            'context': {'default_x_price_group_ids': [(6, 0, [self.id])]},
        }

    def copy(self, default=None):
        """
        Sobrescribe el método copy para manejar la duplicación del agrupador.
        El código se hace único agregando un sufijo.
        """
        if default is None:
            default = {}
        
        # Si se está copiando y hay código, hacerlo único
        if 'code' not in default and self.code:
            default['code'] = f"{self.code}_copy"
        
        # Si se está copiando y hay nombre, hacerlo único
        if 'name' not in default:
            default['name'] = f"{self.name} (Copia)"
        
        return super().copy(default)
