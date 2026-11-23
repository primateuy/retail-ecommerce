# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

class ResCompany(models.Model):
    _inherit = 'res.company'

    fenicio_token = fields.Char(string='Token de Autenticación Fenicio')
    fenicio_website_id = fields.Many2one('website', string='Sitio Web Fenicio')
    fenicio_pricelist_venta_id = fields.Many2one('product.pricelist', string='Lista de Precios de Venta Fenicio')
    fenicio_pricelist_lista_id = fields.Many2one('product.pricelist', string='Lista de Precios Lista Fenicio')
    fenicio_pricelist_alternativo_id = fields.Many2one('product.pricelist', string='Lista de Precios Alternativo Fenicio')
    cantidad_stock_bydefault = fields.Integer(string='Cantidad de Stock a mostrar por defecto')
    fenicio_sale_order_type_id = fields.Many2one('sale.order.type', string='Tipo de Orden de Venta Fenicio')

    fenicio_stock_location_ids = fields.Many2many(
        'stock.location',
        relation='fenicio_res_company_stock_location_rel',
        column1='company_id',
        column2='location_id',
        string='Ubicaciones de Stock Fenicio',
        domain=[('usage', '=', 'internal'), ('fenicio_visible', '=', True)]
    )

    fenicio_canje_max_points = fields.Integer(
        string='Máximo de puntos por canje',
        help='Cantidad máxima de puntos que un cliente puede canjear en una sola '
             'solicitud desde Fenicio. 0 = sin límite.',
    )
    fenicio_canje_point_value = fields.Float(
        string='Valor del punto',
        default=1.0,
        help='Monto en la moneda de la compañía que descuenta cada punto canjeado.',
    )
    fenicio_canje_min_amount = fields.Float(
        string='Monto mínimo de compra',
        help='Monto mínimo de la compra para poder usar el cupón del canje. 0 = sin mínimo.',
    )
    fenicio_canje_validity_days = fields.Integer(
        string='Días de vigencia del cupón',
        default=30,
    )
    fenicio_canje_free_shipping = fields.Boolean(string='Cupón con envío gratis')
    fenicio_canje_acumula_desc_producto = fields.Boolean(
        string='Acumula con descuentos de producto',
    )
    fenicio_canje_acumula_dmp = fields.Boolean(
        string='Acumula con descuentos por medio de pago',
    )

    @api.constrains('fenicio_canje_max_points', 'fenicio_canje_point_value',
                    'fenicio_canje_min_amount', 'fenicio_canje_validity_days')
    def _check_fenicio_canje_config(self):
        """Impide valores negativos en la configuración del canje de puntos.

        Raises:
            ValidationError: si algún valor es negativo o la vigencia es menor a un día.
        """
        for company in self:
            if (company.fenicio_canje_max_points < 0
                    or company.fenicio_canje_point_value < 0
                    or company.fenicio_canje_min_amount < 0):
                raise ValidationError(_("Los valores del canje de puntos no pueden ser negativos."))
            if company.fenicio_canje_validity_days < 1:
                raise ValidationError(_("El cupón del canje debe tener al menos un día de vigencia."))

    @api.constrains('fenicio_token')
    def _check_fenicio_token_unique(self):
        for rec in self:
            if rec.fenicio_token:
                duplicate = self.search([
                    ('fenicio_token', '=', rec.fenicio_token),
                    ('id', '!=', rec.id)
                ])
                if duplicate:
                    raise ValidationError("El token de Fenicio ya está siendo utilizado por la compañía: %s. Cada compañía debe tener un token único." % duplicate[0].name)

    @api.constrains('fenicio_website_id')
    def _check_fenicio_website_unique(self):
        for rec in self:
            if rec.fenicio_website_id:
                duplicate = self.search([
                    ('fenicio_website_id', '=', rec.fenicio_website_id.id),
                    ('id', '!=', rec.id)
                ])
                if duplicate:
                    raise ValidationError("El sitio web '%s' ya está asignado a la integración de Fenicio en la compañía: %s." % (rec.fenicio_website_id.name, duplicate[0].name))
