# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fenicio_canje_max_points = fields.Integer(
        related='company_id.fenicio_canje_max_points', readonly=False)
    fenicio_canje_point_value = fields.Float(
        related='company_id.fenicio_canje_point_value', readonly=False)
    fenicio_canje_min_amount = fields.Float(
        related='company_id.fenicio_canje_min_amount', readonly=False)
    fenicio_canje_validity_days = fields.Integer(
        related='company_id.fenicio_canje_validity_days', readonly=False)
    fenicio_canje_free_shipping = fields.Boolean(
        related='company_id.fenicio_canje_free_shipping', readonly=False)
    fenicio_canje_acumula_desc_producto = fields.Boolean(
        related='company_id.fenicio_canje_acumula_desc_producto', readonly=False)
    fenicio_canje_acumula_dmp = fields.Boolean(
        related='company_id.fenicio_canje_acumula_dmp', readonly=False)
