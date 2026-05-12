# -*- coding: utf-8 -*-
from odoo import api, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        """
        Extiende la búsqueda de órdenes pagadas para quitar la restricción
        de compañía, manteniendo la lógica estándar de Odoo (mismo POS/config
        y misma moneda que el POS actual).

        Por qué sudo en vez de ampliar el contexto multi-company:
        la rule de core `point_of_sale.rule_pos_multi_company` aplica el
        filtro `('company_id','in', company_ids)`, donde `company_ids` se
        resuelve desde `context.allowed_company_ids` y, en su defecto, desde
        `user.company_ids.ids`. Para usuarios PDV de sucursal -que tienen
        UNA SOLA company asignada- ampliar el contexto no agrega nada: solo
        pueden poner ahí lo que tienen. El sudo() bypassea esa rule y permite
        ver órdenes de toda la organización desde el POS, sin necesidad de
        asignar más companies al usuario en el backend.

        Riesgos asumidos: el frontend del POS puede recibir órdenes de
        otras companies/sucursales; los métodos de pago de esas órdenes
        pueden no estar cargados en la sesión actual (la búsqueda del super
        ya filtra por mismo config_id y misma currency, así que el riesgo
        es acotado).
        """
        # sudo() bypassa la rule multi-company de core; el resto de los
        # filtros (config_id, currency, dominio del frontend) viaja por el super.
        return super(PosOrder, self.sudo()).search_paid_order_ids(
            config_id, domain, limit, offset)

    def export_for_ui(self):
        """
        Exporta órdenes para la UI usando sudo() para que el cajero pueda
        leer órdenes de otras companies devueltas por search_paid_order_ids.

        Sin esto, los ids devueltos por el sudo() de arriba serían inválidos
        al intentar leerlos como el usuario real (rule multi-company sigue
        aplicando en el read).
        """
        return super(PosOrder, self.sudo()).export_for_ui()
