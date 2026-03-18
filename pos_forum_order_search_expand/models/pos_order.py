# -*- coding: utf-8 -*-
from odoo import api, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        """
        Extiende la búsqueda de órdenes pagadas para quitar la restricción
        de compañía, pero manteniendo la lógica estándar de Odoo
        (mismo POS/config y misma moneda que el POS actual).

        Esto evita romper supuestos del frontend (por ejemplo, que todos
        los pagos usen métodos de pago cargados en la sesión actual),
        pero permite ver órdenes de todas las compañías a las que el
        usuario tiene acceso.
        """
        # Forzar contexto multi-compañía; el resto de la lógica se delega
        # a la implementación estándar de Odoo.
        self = self.with_context(allowed_company_ids=self.env.user.company_ids.ids)
        return super().search_paid_order_ids(config_id, domain, limit, offset)

    def export_for_ui(self):
        """
        Exporta órdenes para la UI considerando compañías permitidas.

        Returns:
            list: Órdenes exportadas para el POS.
        """
        # Forzar contexto multi-compañía para el usuario actual
        orders = self.with_context(allowed_company_ids=self.env.user.company_ids.ids)
        # Ejecutar exportación estándar con el contexto ampliado
        return super(PosOrder, orders).export_for_ui()
