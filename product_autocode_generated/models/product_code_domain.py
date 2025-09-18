from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductCodeDomain(models.Model):
    _name = 'product.code.domain'
    _description = 'Dominio de código para productos'

    name = fields.Char(
        string='Nombre del dominio',
        required=True,
        help='Nombre descriptivo del dominio (ej: Ropa Masculina, Calzado Deportivo)',
        translate=False,
        index=True,
    )
    
    code = fields.Char(
        string='Código del dominio',
        required=True,
        size=20,
        help='Código corto y único del dominio (ej: M, DEP, CAS). Máximo 20 caracteres.',
        index=True,
    )
    
    active = fields.Boolean(
        string='Activo',
        default=True,
        help='Indica si este dominio está activo y disponible para uso',
    )

    @api.constrains('code')
    def check_unique_code(self):
        for rec in self:
            ids = self.env['product.code.domain'].search([('code', '=', rec.code)], limit=2)
            if len(ids) == 2:
                raise ValidationError(f'Ya existe un dominio con el código {rec.code}')
