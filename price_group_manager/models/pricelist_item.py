from odoo import models, fields, api


class PricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    aplicar_agrupador = fields.Boolean('Aplicar agrupador', default=False)
    price_group_id = fields.Many2one('x_price_group', 'Agrupador de Precio', help='Agrupador de precio específico para aplicar esta regla')

    @api.onchange('aplicar_agrupador')
    def change_aplicar_agrupador(self):
        for rec in self:
            if rec.aplicar_agrupador:
                rec.applied_on = '3_global'

    def _is_applicable_for(self, product, qty_in_product_uom):
        """Check whether the current rule is valid for the given product & qty.

        Note: self.ensure_one()

        :param product: product record (product.product/product.template)
        :param float qty_in_product_uom: quantity, expressed in product UoM
        :returns: Whether rules is valid or not
        :rtype: bool
        """
        self.ensure_one()
        product.ensure_one()
        res = True

        is_product_template = product._name == 'product.template'
        if self.min_quantity and qty_in_product_uom < self.min_quantity:
            res = False

        elif self.applied_on == "2_product_category":
            if (
                product.categ_id != self.categ_id
                and not product.categ_id.parent_path.startswith(self.categ_id.parent_path)
            ):
                res = False
        else:
            # Applied on a specific product template/variant
            if is_product_template:
                if self.applied_on == "1_product" and product.id != self.product_tmpl_id.id:
                    res = False
                elif self.applied_on == "0_product_variant" and not (
                    product.product_variant_count == 1
                    and product.product_variant_id.id == self.product_id.id
                ):
                    # product self acceptable on template if has only one variant
                    res = False
            else:
                if self.applied_on == "1_product" and product.product_tmpl_id.id != self.product_tmpl_id.id:
                    res = False
                elif self.applied_on == "0_product_variant" and product.id != self.product_id.id:
                    res = False

        if self.aplicar_agrupador and self.price_group_id:
            product._compute_current_price_group()
            if product.x_current_price_group_id != self.price_group_id:
                res = False

        return res

    # @api.depends('price_group_id')
    # def _compute_price_group_info(self):
    #     """
    #     Calcula información descriptiva del agrupador seleccionado.
    #     """
    #     for record in self:
    #         if record.price_group_id:
    #             record.price_group_info = f"{record.price_group_id.name} ({record.price_group_id.code or 'Sin código'})"
    #         else:
    #             record.price_group_info = False
    #
    # @api.constrains('applied_on', 'price_group_id')
    # def _check_price_group_consistency(self):
    #     """
    #     Valida que cuando se selecciona 'price_group', se especifique un agrupador.
    #     """
    #     for record in self:
    #         if record.applied_on == 'price_group' and not record.price_group_id:
    #             raise ValidationError(_(
    #                 'Debe seleccionar un agrupador de precio cuando el criterio '
    #                 'de aplicación es "Agrupador de Precio del Producto".'
    #             ))
    #
    # @api.onchange('applied_on')
    # def _onchange_applied_on(self):
    #     """
    #     Limpia campos relacionados cuando cambia el criterio de aplicación.
    #     """
    #     if self.applied_on != 'price_group':
    #         self.price_group_id = False
    #
    # def _is_applicable_for_product(self, product, date=None, **kwargs):
    #     """
    #     Sobrescribe el método para verificar si la regla es aplicable
    #     según el agrupador de precio del producto.
    #     """
    #     # Si no es una regla de agrupador de precio, usar la lógica estándar
    #     if self.applied_on != 'price_group':
    #         return super()._is_applicable_for_product(product, date, **kwargs)
    #
    #     # Verificar que se haya especificado un agrupador
    #     if not self.price_group_id:
    #         return False
    #
    #     # Obtener el agrupador vigente del producto para la fecha especificada
    #     product_price_group = product.get_price_group_for_date(date)
    #
    #     # La regla es aplicable si el agrupador del producto coincide
    #     return product_price_group == self.price_group_id
    #
    # def _get_product_price(self, product, quantity, uom, date, **kwargs):
    #     """
    #     Sobrescribe el método para obtener el precio del producto
    #     considerando agrupadores de precio.
    #     """
    #     # Si no es una regla de agrupador de precio, usar la lógica estándar
    #     if self.applied_on != 'price_group':
    #         return super()._get_product_price(product, quantity, uom, date, **kwargs)
    #
    #     # Verificar que la regla sea aplicable
    #     if not self._is_applicable_for_product(product, date, **kwargs):
    #         return 0.0
    #
    #     # Usar la lógica estándar para calcular el precio
    #     return super()._get_product_price(product, quantity, uom, date, **kwargs)
    #
    # def _get_product_price_rule(self, product, quantity, uom, date, **kwargs):
    #     """
    #     Sobrescribe el método para obtener la regla de precio del producto
    #     considerando agrupadores de precio.
    #     """
    #     # Si no es una regla de agrupador de precio, usar la lógica estándar
    #     if self.applied_on != 'price_group':
    #         return super()._get_product_price_rule(product, quantity, uom, date, **kwargs)
    #
    #     # Verificar que la regla sea aplicable
    #     if not self._is_applicable_for_product(product, date, **kwargs):
    #         return False
    #
    #     # Usar la lógica estándar para obtener la regla
    #     return super()._get_product_price_rule(product, quantity, uom, date, **kwargs)
    #
    # def _get_product_price_rule_multi(self, products, quantity, uom, date, **kwargs):
    #     """
    #     Sobrescribe el método para obtener reglas de precio múltiples
    #     considerando agrupadores de precio.
    #     """
    #     # Si no es una regla de agrupador de precio, usar la lógica estándar
    #     if self.applied_on != 'price_group':
    #         return super()._get_product_price_rule_multi(products, quantity, uom, date, **kwargs)
    #
    #     # Filtrar productos que tengan el agrupador correcto
    #     applicable_products = products.filtered(
    #         lambda p: self._is_applicable_for_product(p, date, **kwargs)
    #     )
    #
    #     if not applicable_products:
    #         return {}
    #
    #     # Usar la lógica estándar para los productos aplicables
    #     return super()._get_product_price_rule_multi(applicable_products, quantity, uom, date, **kwargs)
    #
    # def get_applicable_products(self, date=None):
    #     """
    #     Obtiene los productos a los que se puede aplicar esta regla
    #     según el agrupador de precio.
    #
    #     Args:
    #         date (date): Fecha para la cual verificar la aplicabilidad
    #
    #     Returns:
    #         recordset: Productos a los que se puede aplicar la regla
    #     """
    #     if self.applied_on != 'price_group' or not self.price_group_id:
    #         return self.env['product.product']
    #
    #     # Buscar productos que tengan este agrupador vigente en la fecha
    #     domain = [
    #         ('x_price_group_line_ids.price_group_id', '=', self.price_group_id.id),
    #         ('x_price_group_line_ids.active', '=', True)
    #     ]
    #
    #     if date:
    #         domain.extend([
    #             '|',
    #             ('x_price_group_line_ids.date_start', '<=', date),
    #             ('x_price_group_line_ids.date_start', '=', False)
    #         ])
    #         domain.extend([
    #             '|',
    #             ('x_price_group_line_ids.date_end', '>=', date),
    #             ('x_price_group_line_ids.date_end', '=', False)
    #         ])
    #
    #     return self.env['product.product'].search(domain)
    #
    # def action_view_applicable_products(self):
    #     """
    #     Acción para ver los productos a los que se puede aplicar esta regla.
    #     """
    #     self.ensure_one()
    #
    #     if self.applied_on != 'price_group':
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'display_notification',
    #             'params': {
    #                 'title': _('Información'),
    #                 'message': _('Esta regla no es de tipo "Agrupador de Precio".'),
    #                 'type': 'info',
    #             }
    #         }
    #
    #     # Obtener productos aplicables
    #     products = self.get_applicable_products()
    #
    #     return {
    #         'name': _('Productos Aplicables: %s') % self.price_group_id.name,
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'product.product',
    #         'view_mode': 'tree,form',
    #         'domain': [('id', 'in', products.ids)],
    #         'context': {'default_x_price_group_ids': [(6, 0, [self.price_group_id.id])]},
    #     }
    #
    # @api.model
    # def create(self, vals):
    #     """
    #     Sobrescribe el método create para validar la consistencia
    #     de reglas de agrupador de precio.
    #     """
    #     # Crear el item
    #     item = super().create(vals)
    #
    #     # Validar consistencia
    #     if item.applied_on == 'price_group' and not item.price_group_id:
    #         raise ValidationError(_(
    #             'Debe especificar un agrupador de precio para reglas de tipo '
    #             '"Agrupador de Precio del Producto".'
    #         ))
    #
    #     return item
    #
    # def write(self, vals):
    #     """
    #     Sobrescribe el método write para validar la consistencia
    #     de reglas de agrupador de precio.
    #     """
    #     # Actualizar el item
    #     result = super().write(vals)
    #
    #     # Validar consistencia después de la actualización
    #     for record in self:
    #         if record.applied_on == 'price_group' and not record.price_group_id:
    #             raise ValidationError(_(
    #                 'Debe especificar un agrupador de precio para reglas de tipo '
    #                 '"Agrupador de Precio del Producto".'
    #             ))
    #
    #     return result
