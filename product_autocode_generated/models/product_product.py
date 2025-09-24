import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    auto_code_enabled_product = fields.Boolean('Habilitar códigos automáticos', default=True)

    def codificar(self, final_code=False):
        for rec in self:
            if not final_code:
                if not rec.auto_code_enabled_product:
                    continue

                if not rec.product_tmpl_id.default_code:
                    continue

            codigo_template = final_code or rec.product_tmpl_id.default_code

            atributo_valor_ids = rec.product_template_attribute_value_ids

            ids_atributos = atributo_valor_ids.mapped('attribute_id').filtered(lambda l: l.include_in_code).ids

            dict_atributo_code = {}
            for atributo_valor_id in atributo_valor_ids:
                if atributo_valor_id.attribute_id.include_in_code:
                    dict_atributo_code[atributo_valor_id.attribute_id] = atributo_valor_id.product_attribute_value_id.code or ''

            atributos_ids = self.env['product.attribute'].search([('id', 'in', ids_atributos)])
            for atributo_id in atributos_ids:
                if atributo_id in dict_atributo_code and dict_atributo_code[atributo_id]:
                    codigo_template += dict_atributo_code[atributo_id]

            rec.write({
                'default_code': codigo_template,
            })

            rec.write({
                'default_code': codigo_template,
            })
