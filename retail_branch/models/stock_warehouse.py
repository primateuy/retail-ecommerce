# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StockWarehouse(models.Model):
    """El almacén es la sucursal.

    No se crea un modelo aparte a propósito: el almacén ya es la entidad que tiene
    ubicaciones, tipos de operación y reglas de reabastecimiento, que es todo lo que
    define operativamente a un local. Un modelo nuevo solo agregaría una tabla que
    habría que mantener sincronizada con el almacén.
    """
    _inherit = 'stock.warehouse'

    is_branch = fields.Boolean(
        string='Es sucursal',
        default=False,
        index=True,
        copy=False,
        help='Distingue los locales de los almacenes que no lo son, como el centro de '
             'distribución o el laboratorio.',
    )
    branch_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='stock_warehouse_branch_user_rel',
        column1='warehouse_id',
        column2='user_id',
        string='Usuarios de la sucursal',
        copy=False,
        help='Usuarios que operan esta sucursal. Bajo uno de estos usuarios los '
             'empleados del local abren la sesión de caja.',
    )
    branch_pos_config_ids = fields.Many2many(
        comodel_name='pos.config',
        relation='stock_warehouse_branch_pos_config_rel',
        column1='warehouse_id',
        column2='pos_config_id',
        string='PDV de la sucursal',
        copy=False,
        help='Puntos de venta del local.',
    )
    branch_pos_company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía de facturación',
        compute='_compute_branch_pos_company_id',
        store=True,
        ondelete='restrict',
        help='Compañía bajo la cual factura el local, derivada de sus PDV. Puede ser '
             'distinta de la compañía del almacén: ese es justamente el caso de una '
             'sucursal de franquicia.',
    )

    # El Many2many de PDV va deliberadamente SIN check_company. El PDV de una sucursal
    # de franquicia pertenece a la compañía de la franquicia mientras que el almacén
    # pertenece a la casa central, y check_company rechazaría esa combinación, que es la
    # que el negocio necesita.

    @api.depends('branch_pos_config_ids.company_id')
    def _compute_branch_pos_company_id(self):
        for warehouse in self:
            companies = warehouse.branch_pos_config_ids.company_id
            warehouse.branch_pos_company_id = companies[:1] if companies else False

    @api.constrains('branch_pos_config_ids')
    def _check_branch_pos_single_company(self):
        """Los PDV de una sucursal tienen que facturar todos bajo la misma compañía.

        Si no, la compañía de facturación del local es ambigua y la sincronización de
        company_ids no sabría qué agregarle al usuario.
        """
        for warehouse in self:
            companies = warehouse.branch_pos_config_ids.company_id
            if len(companies) > 1:
                raise ValidationError(_(
                    'Los PDV de la sucursal "%(warehouse)s" pertenecen a más de una '
                    'compañía (%(companies)s). Una sucursal factura bajo una sola '
                    'compañía.',
                    warehouse=warehouse.display_name,
                    companies=', '.join(companies.mapped('name')),
                ))

    def _branch_company_ids(self):
        """Compañías que un usuario necesita para operar estas sucursales."""
        return self.company_id | self.branch_pos_config_ids.company_id

    def _clear_branch_cache(self):
        """Invalida el caché de reglas.

        generic_security_restriction cachea ir.rule._compute_domain con ormcache sobre
        el uid, y solo limpia ese caché cuando cambian groups_id. Los dominios del perfil
        de sucursal dependen de branch_warehouse_ids, así que hay que limpiarlo también
        acá o el cambio no surte efecto hasta reiniciar el servidor.
        """
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        if any(v.get('branch_user_ids') or v.get('branch_pos_config_ids') for v in vals_list):
            warehouses._clear_branch_cache()
        warehouses.branch_user_ids._sync_branch_companies()
        return warehouses

    def write(self, vals):
        # Los usuarios que salen de la sucursal también necesitan que se les recalcule
        # el caché, así que se capturan antes de escribir.
        previous_users = self.branch_user_ids
        result = super().write(vals)
        if {'branch_user_ids', 'branch_pos_config_ids'} & set(vals):
            self._clear_branch_cache()
            (previous_users | self.branch_user_ids)._sync_branch_companies()
        return result
