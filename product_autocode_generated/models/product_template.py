import logging
import sys

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

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
    )

    codigo_template = fields.Char('Código plantilla', tracking=True)

    @api.model
    def get_final_code(self, s_code):
        ICP = self.env['ir.config_parameter']
        total_len_param = int(ICP.get_param('product_auto_code_v2.total_length'))

        if total_len_param == 0:
            padding = 1
        else:
            if len(s_code) >= total_len_param:
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
            if rec.codigo_template:
                continue

            if not rec.auto_code_enabled:
                raise UserError(f'No están habilitados los códigos automáticos en el producto {rec.display_name}')

            if not rec.categ_id.code:
                raise UserError(f'No está habilitado el código de la categoría en el producto {rec.display_name}')

            if not rec.code_domain_id:
                raise UserError(f'No está habilitado la Versión / Origen en el producto {rec.display_name}')

        for rec in self:
            s_code = f'{rec.categ_id.code}{rec.code_domain_id.code}'

            if rec.codigo_template:
                continue

            if rec.product_variant_count == 1:
                final_code = rec.get_final_code(s_code)
                rec.write({
                    'default_code': final_code,
                    'codigo_template': final_code,
                })
            else:
                final_code = s_code
                rec.write({
                    'codigo_template': final_code,
                })

    def codificar_variantes(self):
        for rec in self:
            if rec.product_variant_count > 1:
                rec.product_variant_ids.filtered(lambda l: l.auto_code_enabled_product).codificar()

    def codificar_todo(self):
        for rec in self:
            rec.codificar_plantilla()
            rec.codificar_variantes()
