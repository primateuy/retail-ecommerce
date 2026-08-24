# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    codigo = fields.Char('Código Atributo Fenicio', help='Código del atributo para integración con fenicio');
    fenicio_type = fields.Selection([
        ('variante', 'Variante'),
        ('presentacion', 'Presentación'),
    ], string='Tipo Fenicio', help='Comportamiento de atributos en variantes para integración con fenicio')
    base_product_attribute = fields.Boolean('Es una Característica FENICIO del producto', default=False)
    base_product_attribute_required = fields.Boolean('Atributo obligatorio', default=False)
    fenicio_categoria_ids = fields.Many2many(
        'product.public.category',
        string='Categorías Talle Fenicio',
        help='Categorías de producto (Tienda web) para las que este atributo es el '
             'Talle/Tamaño a usar al importar presentaciones de Fenicio con más de un '
             'talle por variante.'
    )
    fenicio_talle_default = fields.Boolean(
        'Talle Fenicio por defecto',
        default=False,
        help='Atributo Talle a usar al importar un producto Fenicio con más de una '
             'presentación por variante cuando su categoría no tiene un atributo Talle '
             'propio configurado en "Categorías Talle Fenicio". Solo puede haber uno '
             'marcado como default; al marcar este se desmarcan los demás.'
    )

    def write(self, vals):
        res = super().write(vals)
        if vals.get('fenicio_talle_default'):
            self._unset_other_fenicio_talle_default()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(vals.get('fenicio_talle_default') for vals in vals_list):
            records.filtered('fenicio_talle_default')._unset_other_fenicio_talle_default()
        return records

    def _unset_other_fenicio_talle_default(self):
        """Solo puede haber un atributo marcado como Talle Fenicio por defecto."""
        others = self.search([('id', 'not in', self.ids), ('fenicio_talle_default', '=', True)])
        if others:
            others.write({'fenicio_talle_default': False})


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    fenicio_attribute_value_code = fields.Char('Código Variante Fenicio')
    excluir_valor_fenicio = fields.Boolean(
        string='Excluir Valor Fenicio',
        default=False,
        help='Si está activo, este valor no se incluye en el nombre de la variante enviada a Fenicio.'
    )
