# -*- coding: utf-8 -*-
"""Extiende `pos.session` con un RPC que el frontend llama al abrir la
PaymentScreen para obtener los datos del CAE de contingencia activo.

Se eligió RPC bajo demanda en lugar de pre-cargar via `_loader_params_*`
porque los datos del CAE pueden cambiar entre sesiones (admin renueva el
talonario) y la cantidad de datos es pequeña.
"""
from odoo import fields, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def cfc_cae_info(self):
        """Devuelve datos del CAE de contingencia activo para el PDV actual.

        Lee `self.config_id.journal_id` para determinar si es un PDV de
        contingencia. Si lo es, retorna info del CAE activo; si no, retorna
        `{'is_cfc': False}` para que el frontend desactive la lógica CFC.
        """
        self.ensure_one()
        journal = self.config_id.journal_id
        if not journal or not journal.es_diario_contingencia:
            return {'is_cfc': False}
        cae = journal.cae_activo_id
        if not cae:
            return {
                'is_cfc': True,
                'has_cae': False,
                'envio_online': bool(self.config_id.envio_cfc_online),
            }
        return {
            'is_cfc': True,
            'has_cae': True,
            'envio_online': bool(self.config_id.envio_cfc_online),
            'nro_cae': cae.nro_cae,
            'fecha_vencimiento': fields.Date.to_string(cae.fecha_vencimiento),
            'rango_inicial': cae.rango_inicial,
            'rango_final': cae.rango_final,
            'folios_disponibles': cae.folios_disponibles,
        }
