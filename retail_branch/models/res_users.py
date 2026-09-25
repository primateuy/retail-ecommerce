# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    branch_warehouse_ids = fields.Many2many(
        comodel_name='stock.warehouse',
        relation='stock_warehouse_branch_user_rel',
        column1='user_id',
        column2='warehouse_id',
        string='Sucursales',
        copy=False,
        help='Sucursales que opera este usuario. Un usuario de local tiene una; un '
             'supervisor puede tener varias.',
    )

    def _branch_warehouse_ids(self):
        """Ids de las sucursales del usuario, para usar en los dominios del perfil."""
        self.ensure_one()
        return self.branch_warehouse_ids.ids

    def _sync_branch_companies(self):
        """Agrega a company_ids las compañías que la sucursal necesita.

        Las reglas multicompañía de stock y de point_of_sale usan
        ('company_id', 'in', company_ids), sin jerarquía de compañías. Por eso un
        usuario de una franquicia no puede ver un almacén de la casa central aunque su
        compañía sea hija de ella: la jerarquía solo resuelve las reglas que usan
        parent_of, que son las de producto, lista de precios, lealtad y los maestros
        contables.

        Solo agrega. Nunca quita una compañía que el usuario ya tenga, porque puede
        habérsela dado otro proceso por un motivo que este módulo no conoce.
        """
        for user in self:
            warehouses = user.branch_warehouse_ids
            if not warehouses:
                continue
            needed = warehouses._branch_company_ids()
            missing = needed - user.company_ids
            if not missing:
                continue
            _logger.info(
                'Sucursal: se agregan las compañías %s a %s (necesarias para %s)',
                ', '.join(missing.mapped('name')),
                user.login,
                ', '.join(warehouses.mapped('display_name')),
            )
            user.sudo().write({
                'company_ids': [Command.link(company.id) for company in missing],
            })

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        if any(vals.get('branch_warehouse_ids') for vals in vals_list):
            self.env.registry.clear_cache()
            users._sync_branch_companies()
        return users

    def write(self, vals):
        result = super().write(vals)
        if 'branch_warehouse_ids' in vals:
            self.env.registry.clear_cache()
            self._sync_branch_companies()
        return result
