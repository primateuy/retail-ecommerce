# -*- coding: utf-8 -*-
"""
Modelo: terminales pinpad Fiserv ITD (PosID) asociados a un payment.provider.

Se usa cuando el proveedor Fiserv tiene varios POS: cada línea define el PosID
que se enviará en processFinancialPurchase / Query. La URL y SystemId suelen
ser comunes y se toman del proveedor.
"""

from odoo import fields, models


class FiservPosTerminal(models.Model):
    """
    Terminal física / pinpad identificado por PosID para integración Fiserv ITD.

    Utilizado para: seleccionar a qué dispositivo enrutar el cobro cuando el
    proveedor tiene múltiples POS configurados.
    """

    _name = 'fiserv.pos.terminal'
    _description = 'Terminal Fiserv ITD (PosID)'

    name = fields.Char(
        string='Alias',
        required=True,
        help='Nombre descriptivo para identificar la terminal en listas.',
    )
    pos_id = fields.Char(
        string='PosID',
        required=True,
        size=10,
        help='Número de terminal asignado al pinpad/POS por Fiserv (ITD).',
    )
    payment_provider_id = fields.Many2one(
        comodel_name='payment.provider',
        string='Proveedor Fiserv',
        required=True,
        ondelete='cascade',
        domain="[('code', '=', 'fiserv')]",
    )
