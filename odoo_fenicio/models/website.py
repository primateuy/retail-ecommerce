# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.exceptions import ValidationError


class Website(models.Model):
    _inherit = 'website'

    fenicio_token = fields.Char(string='Token de Autenticación Fenicio')
    fenicio_catalog_url = fields.Char(
        string='URL Base API Fenicio (saliente)',
        help='URL base del comercio en Fenicio, ej: https://example.com/. '
             'Se usa para consultar GET /API_V1/catalogo.',
    )
    fenicio_pricelist_venta_id = fields.Many2one('product.pricelist', string='Lista de Precios de Venta Fenicio')
    fenicio_pricelist_lista_id = fields.Many2one('product.pricelist', string='Lista de Precios Lista Fenicio')
    fenicio_pricelist_alternativo_id = fields.Many2one('product.pricelist', string='Lista de Precios Alternativo Fenicio')
    fenicio_cantidad_stock_bydefault = fields.Integer(string='Cantidad de Stock a mostrar por defecto')
    fenicio_sale_order_type_id = fields.Many2one('sale.order.type', string='Tipo de Orden de Venta Fenicio')
    fenicio_payment_journal_id = fields.Many2one(
        'account.journal',
        string='Diario de Pago Fenicio',
        domain="[('type', 'in', ('bank', 'cash'))]",
        help='Diario usado para registrar los pagos de las órdenes Fenicio. '
             'Debe ser de tipo Banco o Efectivo (sin documentos fiscales).',
    )

    fenicio_stock_location_ids = fields.Many2many(
        'stock.location',
        relation='fenicio_website_stock_location_rel',
        column1='website_id',
        column2='location_id',
        string='Ubicaciones de Stock Fenicio',
        domain=[('usage', '=', 'internal'), ('fenicio_visible', '=', True)]
    )

    def _fenicio_ctx(self):
        return {'default_website_id': self.id, 'active_id': self.id, 'active_model': 'website'}

    def action_open_catalog_sync(self):
        self.ensure_one()
        view = self.env.ref('odoo_fenicio.fenicio_catalog_sync_view_form', raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sincronizar Catálogo',
            'res_model': 'fenicio.catalog.sync',
            'view_mode': 'form',
            'views': [(view.id if view else False, 'form')],
            'target': 'new',
            'context': self._fenicio_ctx(),
        }

    def action_open_catalog_test(self):
        self.ensure_one()
        view = self.env.ref('odoo_fenicio.fenicio_catalog_sync_test_view_form', raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sincronización manual',
            'res_model': 'fenicio.catalog.sync',
            'view_mode': 'form',
            'views': [(view.id if view else False, 'form')],
            'target': 'new',
            'context': self._fenicio_ctx(),
        }

    def action_open_catalog_list(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Catálogo Fenicio',
            'res_model': 'fenicio.catalog.line',
            'view_mode': 'tree,form',
            'target': 'current',
        }

    def action_open_catalog_export(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Exportar Catálogo',
            'res_model': 'fenicio.catalog.export',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Logs de Integración',
            'res_model': 'fenicio.log',
            'view_mode': 'tree,form',
            'target': 'current',
            'domain': [('company_id', '=', self.company_id.id)],
        }

    @api.constrains('fenicio_payment_journal_id')
    def _check_fenicio_payment_journal_company(self):
        for rec in self:
            journal = rec.fenicio_payment_journal_id
            if journal and rec.company_id and journal.company_id != rec.company_id:
                raise ValidationError(
                    "El Diario de Pago Fenicio debe pertenecer a la compañía del sitio web (%s)."
                    % rec.company_id.name
                )

    @api.constrains('fenicio_token')
    def _check_fenicio_token_unique(self):
        for rec in self:
            if rec.fenicio_token:
                duplicate = self.search([
                    ('fenicio_token', '=', rec.fenicio_token),
                    ('id', '!=', rec.id)
                ])
                if duplicate:
                    raise ValidationError(
                        "El token de Fenicio ya está siendo utilizado por el sitio web: %s." % duplicate[0].name
                    )