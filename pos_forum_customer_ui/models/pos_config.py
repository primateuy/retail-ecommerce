# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    default_partner_street = fields.Char(
        string="Default Partner Street",
        help="Valor por defecto para Calle al crear clientes desde el POS.",
    )
    default_partner_city = fields.Char(
        string="Default Partner City",
        help="Valor por defecto para Ciudad al crear clientes desde el POS.",
    )
    default_partner_state_id = fields.Many2one(
        "res.country.state",
        string="Default Partner State",
        ondelete="set null",
        help="Departamento por defecto al crear clientes desde el POS y "
             "fallback para el tag <DeptoRecep> del CFE cuando el partner no "
             "tiene state_id cargado.",
    )
    default_partner_country_id = fields.Many2one(
        "res.country",
        string="Default Partner Country",
        ondelete="set null",
        help="País por defecto al crear clientes desde el POS y fallback para "
             "el tag <CodPaisRecep> del CFE cuando el partner no tiene "
             "country_id cargado.",
    )
