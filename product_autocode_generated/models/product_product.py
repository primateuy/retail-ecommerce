import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    auto_code_enabled_product = fields.Boolean('Habilitar códigos automáticos', default=True)

    def codificar(self):
        for rec in self:
            if not rec.auto_code_enabled_product:
                continue

            if not rec.product_tmpl_id.codigo_template:
                continue

            if not rec.categ_id.code:
                raise UserError('No está habilitado el código de la categoría')

            if not rec.code_domain_id:
                raise UserError('No está habilitado la Versión / Origen')

            if rec.product_tmpl_id.product_variant_count == 1:
                raise UserError('Este producto no es una variante')

            s_code = rec.product_tmpl_id.codigo_template

            atributo_valor_ids = rec.product_template_attribute_value_ids

            ids_atributos = atributo_valor_ids.mapped('attribute_id').filtered(lambda l: l.include_in_code).ids

            dict_atributo_code = {}
            for atributo_valor_id in atributo_valor_ids:
                if atributo_valor_id.attribute_id.include_in_code:
                    dict_atributo_code[atributo_valor_id.attribute_id] = atributo_valor_id.product_attribute_value_id.code

            atributos_ids = self.env['product.attribute'].search([('id', 'in', ids_atributos)])
            for atributo_id in atributos_ids:
                if atributo_id in dict_atributo_code and dict_atributo_code[atributo_id]:
                    s_code += dict_atributo_code[atributo_id]

            final_code = rec.product_tmpl_id.get_final_code(s_code)
            rec.write({
                'default_code': final_code,
            })
