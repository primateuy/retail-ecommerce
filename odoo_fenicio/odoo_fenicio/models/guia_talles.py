from odoo import api, fields, models

class GuiaTalles(models.Model):
    _name = 'guia.talles'
    _description = 'Guía de Talles'
    _order = 'sequence, name'

    name = fields.Char(
        string='Nombre',
        required=True,
        help='Nombre descriptivo de la guía de talles'
    )
    
    code = fields.Char(
        string='Código',
        required=True,
        help='Código único para identificar la guía de talles en e-Fenicio'
    )
    
    image = fields.Binary(
        string='Foto',
        attachment=True,
        help='Imagen de la guía de talles'
    )
    
    sequence = fields.Integer(
        string='Secuencia',
        default=10,
        help='Orden de visualización'
    )
    
    active = fields.Boolean(
        string='Activo',
        default=True
    )
    
    description = fields.Text(
        string='Descripción'
    )
    
    _sql_constraints = [
        ('code_unique', 'unique(code)', 'El código de la guía de talles debe ser único!')
    ]
    
    def name_get(self):
        """Mostrar código y nombre en los selects"""
        result = []
        for record in self:
            name = f'[{record.code}] {record.name}'
            result.append((record.id, name))
        return result