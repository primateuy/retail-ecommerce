from odoo import fields, api, models;

import logging;

_logger = logging.getLogger(__name__);


class ProductPriceList(models.Model):
    _inherit = "product.pricelist"

    e_fenicio = fields.Boolean(string='Es lista de precios Fenicio', default=False, help='Indica si la lista de precios es utilizada para la integración con Fenicio.')



