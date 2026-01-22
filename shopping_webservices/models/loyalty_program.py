from odoo import fields, api, models;


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    promocionShopping = fields.Boolean(string="Promoción Shopping", help="Indica si el programa de lealtad está asociado a promociones específicas del shopping.")
    