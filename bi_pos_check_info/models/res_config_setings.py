# -*- coding: utf-8 -*-

from odoo import api, fields, models

class PosConfig(models.Model):
    _inherit = 'pos.config'

    allow_check_info = fields.Boolean(string="Allow Check Info")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_allow_check_info = fields.Boolean(string="Allow Check Info", related="pos_config_id.allow_check_info", readonly=False)


