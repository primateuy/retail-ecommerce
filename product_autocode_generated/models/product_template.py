import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    auto_code_enabled = fields.Boolean(
        string='Habilitar códigos automáticos',
        default=True,
        help='Indica si esta plantilla debe generar códigos automáticamente',
        tracking=True,
    )
    
    code_domain_id = fields.Many2one(
        comodel_name='product.code.domain',
        string='Versión / Origen',
        domain=[('active', '=', True)],
        help='Dominio específico para la generación de códigos de esta plantilla',
        ondelete='restrict',
        default=lambda self: self.env.ref('product_autocode_generated.default_code_domain', raise_if_not_found=False) or False
    )

    # codigo_template = fields.Char('Código plantilla', tracking=True)

    # @api.onchange('default_code')
    # def change_default_codee(self):
    #     for rec in self:
    #         rec.codigo_template = rec.default_code

    @api.model
    def get_final_code(self, s_code, tipo):
        ICP = self.env['ir.config_parameter']

        if tipo == 'template':
            param = 'product_autocode_generated.total_length_template'
        else:
            param = 'product_autocode_generated.total_length_variant'

        total_len_param = int(ICP.get_param(param))

        if total_len_param == 0:
            padding = 1
        else:
            if len(s_code) > total_len_param:
                raise UserError(f'El código {s_code} a generar es mas grande que el total permitido')

            padding = total_len_param - len(s_code)

        s_id = self.env['ir.sequence'].sudo().search([('code', '=', s_code)], limit=1)

        if not s_id:
            vals = {
                'name': s_code,
                'code': s_code,
                'padding': padding,
                'prefix': s_code,
            }
            s_id = self.env['ir.sequence'].sudo().create(vals)

        if s_id.padding != padding:
            s_id.sudo().write({
                'padding': padding,
            })

        final_code = s_id.next_by_code(s_code)
        if total_len_param != 0 and len(final_code) > total_len_param:
            raise UserError(f'El código {final_code} generado es mas grande que el total permitido')
        return final_code

    def codificar_plantilla(self):
        for rec in self:
            if not rec.auto_code_enabled:
                raise UserError(f'No están habilitados los códigos automáticos en el producto {rec.display_name}')

            if not rec.categ_id.code:
                raise UserError(f'No está habilitado el código de la categoría en el producto {rec.display_name}')

            if not rec.code_domain_id:
                raise UserError(f'No está habilitado la Versión / Origen en el producto {rec.display_name}')

        for rec in self:
            if rec.product_variant_count == 1:
                s_code = f'{rec.categ_id.code}{rec.code_domain_id.code}'
                final_code = rec.get_final_code(s_code, 'template')
                rec.product_variant_ids.codificar(final_code)
                continue

            s_code = f'{rec.categ_id.code}{rec.code_domain_id.code}'
            final_code = rec.get_final_code(s_code, 'template')
            rec.write({
                'default_code': final_code,
            })

    def codificar_variantes(self):
        for rec in self:
            if rec.product_variant_count == 1:
                s_code = f'{rec.categ_id.code}{rec.code_domain_id.code}'
                final_code = rec.get_final_code(s_code, 'template')
                rec.product_variant_ids.codificar(final_code)
            else:
                rec.product_variant_ids.filtered(lambda l: l.auto_code_enabled_product).codificar()

    def codificar_todo(self):
        for rec in self:
            if rec.product_variant_count == 1:
                rec.codificar_plantilla()
            else:
                rec.codificar_plantilla()
                rec.codificar_variantes()

    def _compute_template_field_from_variant_field(self, fname, default=False):
        """Sets the value of the given field based on the template variant values

        Equals to product_variant_ids[fname] if it's a single variant product.
        Otherwise, sets the value specified in ``default``.
        It's used to compute fields like barcode, weight, volume..

        :param str fname: name of the field to compute
            (field name must be identical between product.product & product.template models)
        :param default: default value to set when there are multiple or no variants on the template
        :return: None
        """
        for template in self:
            variant_count = len(template.product_variant_ids)
            if variant_count == 1:
                template[fname] = template.product_variant_ids[fname]
            elif variant_count == 0 and self.env.context.get("active_test", True):
                # If the product has no active variants, retry without the active_test
                template_ctx = template.with_context(active_test=False)
                template_ctx._compute_template_field_from_variant_field(fname, default=default)
            else:
                if fname == 'default_code' and template.auto_code_enabled:
                    continue
                template[fname] = default
