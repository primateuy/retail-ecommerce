# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    """
    Extiende la configuración del POS para definir el cliente por defecto
    que se asigna al pasar a la pantalla de pago si la orden no tiene cliente.
    """

    _inherit = "pos.config"

    payment_default_customer_id = fields.Many2one(
        comodel_name="res.partner",
        string="Default Customer at Payment",
        help="Cliente que se asigna automáticamente al entrar a la pantalla de pago "
        "cuando la orden no tiene cliente. No modifica órdenes que ya tengan cliente.",
    )
