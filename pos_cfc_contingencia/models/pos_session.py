# -*- coding: utf-8 -*-
"""Extiende `pos.session` con un RPC que el frontend llama al abrir la
PaymentScreen para obtener los datos del CAE de contingencia activo.

Se eligió RPC bajo demanda en lugar de pre-cargar via `_loader_params_*`
porque los datos del CAE pueden cambiar entre sesiones (admin renueva el
talonario) y la cantidad de datos es pequeña.

Lo que sí viaja con la carga es si el PDV ES de contingencia
(`pos.config.cfc_es_contingencia`), para que el frontend pida el folio aunque
este RPC falle.
"""
from odoo import fields, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _get_pos_ui_pos_config(self, params):
        config = super()._get_pos_ui_pos_config(params)
        config['cfc_es_contingencia'] = bool(self.config_id._cfc_journal())
        return config

    def cfc_cae_info(self):
        """Devuelve datos del CAE de contingencia activo para el PDV actual.

        Usa el diario de facturas del PDV (ver `pos.config._cfc_journal`). Si
        es de contingencia retorna info del CAE activo; si no, retorna
        `{'is_cfc': False}` para que el frontend desactive la lógica CFC.

        La lectura del CAE va en sudo: la llamada ya pasó el control de acceso
        del cajero sobre su sesión, y sin sudo un cajero sin grupo contable
        recibía AccessError y el POS dejaba de pedir el folio.
        """
        self.ensure_one()
        journal = self.config_id._cfc_journal()
        if not journal:
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
