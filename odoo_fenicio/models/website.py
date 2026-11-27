# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
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

    fenicio_canje_min_points = fields.Integer(
        string='Mínimo de puntos por canje',
        help='Cantidad mínima de puntos que un cliente debe tener y canjear en cada '
             'solicitud desde Fenicio. 0 = sin mínimo.',
    )
    fenicio_canje_max_points = fields.Integer(
        string='Máximo de puntos por canje',
        help='Cantidad máxima de puntos que un cliente puede canjear en una sola '
             'solicitud desde Fenicio. 0 = sin máximo.',
    )
    fenicio_canje_point_value = fields.Float(
        string='Valor del punto',
        default=1.0,
        help='Monto en la moneda del sitio que descuenta cada punto canjeado.',
    )
    fenicio_canje_min_amount = fields.Float(
        string='Monto mínimo de compra',
        help='Monto mínimo de la compra para poder usar el cupón del canje. 0 = sin mínimo.',
    )
    fenicio_canje_date_start = fields.Date(
        string='Válido desde',
        help='Inicio de la vigencia del cupón del canje. Vacío = sin fecha de inicio.',
    )
    fenicio_canje_date_end = fields.Date(
        string='Válido hasta',
        help='Fin de la vigencia del cupón del canje. Vacío = sin vencimiento.',
    )
    # Códigos de moneda de Fenicio: M1 es la moneda local del comercio, M2 la secundaria.
    fenicio_canje_currency = fields.Selection(
        [('M1', 'M1 - Moneda local'), ('M2', 'M2 - Moneda secundaria')],
        string='Moneda del descuento',
        default='M1',
    )
    fenicio_canje_free_shipping = fields.Boolean(string='Cupón con envío gratis')
    fenicio_canje_acumula_desc_producto = fields.Boolean(
        string='Acumula con descuentos de producto',
    )
    fenicio_canje_acumula_dmp = fields.Boolean(
        string='Acumula con descuentos por medio de pago',
    )
    fenicio_coupon_ids = fields.One2many('fenicio.coupon', 'website_id', string='Cupones Fenicio')

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

    def action_open_coupons(self):
        """Abre los cupones Fenicio de este sitio web.

        Returns:
            dict: action window sobre fenicio.coupon filtrada por el sitio web.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cupones Fenicio',
            'res_model': 'fenicio.coupon',
            'view_mode': 'tree,form',
            'target': 'current',
            'domain': [('website_id', '=', self.id)],
            'context': {'default_website_id': self.id},
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

    def action_open_order_logs(self):
        """Abre los logs del endpoint /orden de este sitio, agrupados por orden Fenicio.

        Returns:
            dict: action window sobre fenicio.log filtrada por compañía y endpoint.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Logs de órdenes Fenicio',
            'res_model': 'fenicio.log',
            'view_mode': 'tree,form',
            'target': 'current',
            'domain': [('company_id', '=', self.company_id.id), ('endpoint', '=', '/orden')],
            'context': {'search_default_group_id_order': 1},
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

    @api.constrains('fenicio_canje_min_points', 'fenicio_canje_max_points',
                    'fenicio_canje_point_value',
                    'fenicio_canje_min_amount', 'fenicio_canje_date_start',
                    'fenicio_canje_date_end')
    def _check_fenicio_canje_config(self):
        """Impide valores negativos en la configuración del canje de puntos.

        Raises:
            ValidationError: si algún valor es negativo, el máximo es menor al mínimo
                o la vigencia termina antes de empezar.
        """
        for website in self:
            if (website.fenicio_canje_min_points < 0
                    or website.fenicio_canje_max_points < 0
                    or website.fenicio_canje_point_value < 0
                    or website.fenicio_canje_min_amount < 0):
                raise ValidationError(_("Los valores del canje de puntos no pueden ser negativos."))
            if (website.fenicio_canje_max_points
                    and website.fenicio_canje_max_points < website.fenicio_canje_min_points):
                raise ValidationError(_(
                    "El máximo de puntos por canje no puede ser menor al mínimo."))
            if (website.fenicio_canje_date_start and website.fenicio_canje_date_end
                    and website.fenicio_canje_date_end < website.fenicio_canje_date_start):
                raise ValidationError(_("La vigencia del canje no puede terminar antes de empezar."))

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