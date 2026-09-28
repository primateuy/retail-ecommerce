# -*- coding: utf-8 -*-
"""
Lo que hace falta de la tarjeta aprobada para verificar la promoción.

El núcleo ya guarda TarjetaId y TarjetaTipo. Para comparar contra el catálogo
faltan el emisor (el banco) y el BIN: ConsultarTransaccion los devuelve
(captura real del 26/09: EmisorId=12 ITAU, TarjetaIIN=421301) y hasta acá se
perdían.
"""

from odoo import fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    getnet_emisor_id = fields.Char(string='Emisor (Getnet)', readonly=True, copy=False)
    getnet_tarjeta_iin = fields.Char(
        string='BIN (Getnet)', readonly=True, copy=False,
        help='Los primeros dígitos de la tarjeta (TarjetaIIN). No es el número.')

    def getnet_persist_query_result(self, result):
        data = (result or {}).get('data') or {}
        vals = {}
        if data.get('EmisorId') not in (None, ''):
            vals['getnet_emisor_id'] = str(data['EmisorId'])
        if data.get('TarjetaIIN') not in (None, ''):
            vals['getnet_tarjeta_iin'] = str(data['TarjetaIIN'])
        if vals:
            self.write(vals)
        return super().getnet_persist_query_result(result)

    def getnet_tarjeta_aprobada(self):
        """La tarjeta que pagó, en el formato del catálogo."""
        self.ensure_one()
        return {
            'tarjeta_id': self.getnet_tarjeta_id or '',
            'emisor_id': self.getnet_emisor_id or '',
            'tarjeta_tipo': self.getnet_tarjeta_tipo or '',
            'iin': self.getnet_tarjeta_iin or '',
        }
