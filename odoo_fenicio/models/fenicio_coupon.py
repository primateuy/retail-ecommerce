# -*- coding: utf-8 -*-

from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FenicioCoupon(models.Model):
    """Cupón externo que Fenicio consulta por código en el checkout (GET /cupon).

    Fenicio reconoce los cupones externos por un prefijo fijo de 3 o 4 caracteres en el
    código (ej. PRExxxxx), que se configura del lado de Fenicio.
    """
    _name = 'fenicio.coupon'
    _description = 'Cupón Fenicio'
    _order = 'website_id, date_start desc, code'
    _rec_name = 'code'

    _sql_constraints = [
        ('code_website_uniq', 'unique(website_id, code)',
         "Ya existe un cupón con ese código en el sitio web."),
    ]

    active = fields.Boolean(default=True)
    website_id = fields.Many2one(
        'website',
        string='Sitio web',
        required=True,
        ondelete='cascade',
        default=lambda self: self.env['website'].search(
            [('company_id', '=', self.env.company.id)], limit=1),
    )
    code = fields.Char(string='Código', size=128, required=True)
    description = fields.Char(
        string='Descripción',
        size=32,
        required=True,
        help='Visible para el cliente en el checkout de Fenicio al ingresar el cupón.',
    )
    discount_type = fields.Selection(
        [('montofijo', 'Monto fijo'), ('porcentaje', 'Porcentaje')],
        string='Tipo de descuento',
        required=True,
        default='montofijo',
    )
    discount_value = fields.Float(string='Valor del descuento', required=True)
    # Códigos de moneda de Fenicio: M1 es la moneda local del comercio, M2 la secundaria.
    discount_currency = fields.Selection(
        [('M1', 'M1 - Moneda local'), ('M2', 'M2 - Moneda secundaria')],
        string='Moneda del descuento',
        default='M1',
    )
    min_amount = fields.Float(
        string='Monto mínimo de compra',
        help='Monto mínimo de la compra para aplicar el cupón. 0 = sin mínimo.',
    )
    product_groups = fields.Char(
        string='Grupos de productos',
        size=128,
        help='Números de grupo de Fenicio separados por coma. Se toman de la URL del '
             'catálogo: en https://tutienda.com.uy/catalogo?grp=54 el grupo es 54.',
    )
    date_start = fields.Date(string='Válido desde', help='Vacío = sin fecha de inicio.')
    date_end = fields.Date(string='Válido hasta', help='Vacío = sin vencimiento.')
    is_free_shipping = fields.Boolean(string='Envío gratis')
    is_cumulative_product_discount = fields.Boolean(
        string='Acumula con descuentos de producto', default=True)
    is_cumulative_payment_discount = fields.Boolean(
        string='Acumula con descuentos por medio de pago', default=True)
    sale_order_ids = fields.Many2many(
        'sale.order',
        relation='fenicio_coupon_sale_order_rel',
        column1='coupon_id',
        column2='sale_order_id',
        string='Pedidos',
        readonly=True,
        copy=False,
    )
    sale_order_count = fields.Integer(string='Usos', compute='_compute_sale_order_count')

    @api.depends('sale_order_ids')
    def _compute_sale_order_count(self):
        for coupon in self:
            coupon.sale_order_count = len(coupon.sale_order_ids)

    def action_view_sale_orders(self):
        """Abre los pedidos de venta de Fenicio en los que se usó el cupón.

        Returns:
            dict: action window sobre sale.order filtrada por los pedidos del cupón.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pedidos con el cupón %s", self.code),
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.sale_order_ids.ids)],
        }

    @api.onchange('discount_type')
    def _onchange_discount_type(self):
        """Marca los acumulables que Fenicio exige en los cupones de monto fijo."""
        if self.discount_type == 'montofijo':
            self.is_cumulative_product_discount = True
            self.is_cumulative_payment_discount = True

    @api.constrains('discount_type', 'discount_value', 'min_amount',
                    'is_cumulative_product_discount', 'is_cumulative_payment_discount')
    def _check_discount(self):
        """Valida el descuento según las reglas de la documentación de Fenicio.

        Raises:
            ValidationError: si el valor o el mínimo no son válidos, el porcentaje
                supera 100, o un cupón de monto fijo no acumula con los demás descuentos.
        """
        for coupon in self:
            if coupon.discount_value <= 0 or coupon.min_amount < 0:
                raise ValidationError(_(
                    "El cupón %s debe tener un descuento mayor a cero y un mínimo no negativo.",
                    coupon.code))
            if coupon.discount_type == 'porcentaje' and coupon.discount_value > 100:
                raise ValidationError(_(
                    "El descuento del cupón %s no puede superar el 100%%.", coupon.code))
            if coupon.discount_type == 'montofijo' and not (
                    coupon.is_cumulative_product_discount
                    and coupon.is_cumulative_payment_discount):
                raise ValidationError(_(
                    "Fenicio exige que los cupones de monto fijo acumulen con descuentos de "
                    "producto y por medio de pago (cupón %s).", coupon.code))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Impide que la vigencia termine antes de empezar.

        Raises:
            ValidationError: si 'Válido hasta' es anterior a 'Válido desde'.
        """
        for coupon in self:
            if coupon.date_start and coupon.date_end and coupon.date_end < coupon.date_start:
                raise ValidationError(_(
                    "El cupón %s no puede terminar antes de empezar.", coupon.code))

    @api.model
    def _get_fenicio_coupon(self, website, code):
        """Busca un cupón activo y no vencido del sitio web por su código.

        Args:
            website (website): sitio web dueño del token de Fenicio.
            code (str): código ingresado por el cliente en Fenicio.

        Returns:
            fenicio.coupon: el cupón encontrado.

        Raises:
            UserError: si el cupón no existe, está archivado o ya venció.
        """
        coupon = self.search([('website_id', '=', website.id), ('code', '=', code)], limit=1)
        if not coupon:
            raise UserError(_("El cupón no existe."))
        # La vigencia se evalúa con el día de Montevideo, igual que las fechas que se devuelven.
        today = datetime.now(pytz.timezone('America/Montevideo')).date()
        if coupon.date_end and coupon.date_end < today:
            raise UserError(_("El cupón está vencido."))
        return coupon

    def _get_fenicio_data(self):
        """Arma el 'data' de la respuesta de GET /cupon según la documentación de Fenicio.

        Returns:
            dict: condiciones del cupón. Las fechas sin cargar van como null.
        """
        self.ensure_one()
        api_internal = self.env['api.internal']
        return {
            'codigocupon': self.code,
            'tipodescuento': self.discount_type,
            'valordescuento': api_internal._format_monto_canje(self.discount_value),
            'monedadescuento': self.discount_currency or 'M1',
            'montominimo': api_internal._format_monto_canje(self.min_amount),
            'grupos': self.product_groups or '',
            'descripcion': self.description,
            'validodesde': api_internal._format_fecha_fenicio(self.date_start, time.min, None),
            'validohasta': api_internal._format_fecha_fenicio(self.date_end, time(23, 59), None),
            'enviogratis': self.is_free_shipping,
            'acumuladescproducto': self.is_cumulative_product_discount,
            'acumuladmp': self.is_cumulative_payment_discount,
        }
