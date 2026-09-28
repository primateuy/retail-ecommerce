# -*- coding: utf-8 -*-
"""Cómo se anuncia este módulo ante el POS (contrato §3.1).

Dos cosas, y son las únicas que el POS necesita: agregar la propia opción a la
lista de proveedores —que nace vacía— y devolver la implementación cuando el
POS pregunta por ese proveedor. El POS no conoce el nombre de este módulo.

Y una tercera que es nuestra: QUÉ pinpad atiende esta caja. El proveedor
Getnet puede tener varias terminales y el POS no tiene por qué saberlo.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosBackendBoxPaymentMethod(models.Model):
    _inherit = 'pos_backend.box.payment.method'

    terminal_provider = fields.Selection(
        selection_add=[('getnet', 'Getnet / TransAct')],
        ondelete={'getnet': 'set null'},
    )
    getnet_terminal_id = fields.Many2one(
        comodel_name='getnet.pos.terminal',
        string='Terminal Getnet',
        ondelete='restrict',
        help='El pinpad que atiende esta caja. El lock de la terminal es '
             'entre flujos: si el mismo pinpad lo usa también el cobro '
             'contable o el TPV, se excluyen solos.',
    )

    def _get_terminal_implementation(self, provider):
        if provider == 'getnet':
            return self.env['pos_backend.terminal.getnet']
        return super()._get_terminal_implementation(provider)

    @api.constrains('terminal_provider', 'getnet_terminal_id')
    def _check_getnet_terminal(self):
        """Elegir Getnet sin decir qué pinpad no cobra nada, y hay que decirlo.

        El POS ya bloquea un medio integrado sin proveedor porque «nadie
        verificaría la transacción». Esto es el mismo agujero un nivel más
        abajo: proveedor elegido y ninguna terminal a la que hablarle.
        """
        for medio in self:
            if medio.terminal_provider == 'getnet' and not medio.getnet_terminal_id:
                raise ValidationError(_(
                    'El medio «%s» está configurado con la terminal Getnet '
                    'pero no tiene ningún pinpad asignado, así que no hay a '
                    'quién pedirle la autorización. Elegí la terminal Getnet '
                    'en el medio de pago.') % medio.name)
