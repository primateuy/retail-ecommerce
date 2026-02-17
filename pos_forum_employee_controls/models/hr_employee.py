# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    pos_allow_refund_button = fields.Boolean(
        string="POS: Allow Refund Button",
        default=True,
    )
    pos_allow_pricelist_button = fields.Boolean(
        string="POS: Allow Pricelist Button",
        default=True,
    )
    pos_allow_customer_note_button = fields.Boolean(
        string="POS: Allow Customer Note Button",
        default=True,
    )
    pos_allow_discount_button = fields.Boolean(
        string="POS: Allow Discount Button",
        default=True,
    )
    pos_allow_salesperson_button = fields.Boolean(
        string="POS: Allow Salesperson Button",
        default=True,
    )
    pos_allow_z_report_button = fields.Boolean(
        string="POS: Allow Z Report Button",
        default=True,
    )
    pos_allow_ewallet_button = fields.Boolean(
        string="POS: Allow eWallet Button",
        default=True,
    )
    pos_allow_promo_code_button = fields.Boolean(
        string="POS: Allow Promo Code Button",
        default=True,
    )
    pos_allow_reward_button = fields.Boolean(
        string="POS: Allow Reward Button",
        default=True,
    )
    pos_allow_reset_programs_button = fields.Boolean(
        string="POS: Allow Reset Programs Button",
        default=True,
    )
    pos_allow_quotation_button = fields.Boolean(
        string="POS: Allow Quotation Button",
        default=True,
    )
    pos_allow_numpad_discount = fields.Boolean(
        string="POS: Allow Numpad Discount",
        default=True,
    )
    pos_allow_numpad_price = fields.Boolean(
        string="POS: Allow Numpad Price",
        default=True,
    )
