# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import datetime

from odoo import api, models
from odoo.osv.expression import AND


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        """
        Busca órdenes pagadas sin filtrar por PDV o compañía.

        Args:
            config_id (int): Configuración POS actual (se ignora para el filtro).
            domain (list): Dominio adicional desde la UI.
            limit (int): Límite de resultados.
            offset (int): Offset para paginación.

        Returns:
            dict: Información de órdenes y total de resultados.
        """
        # Definir el dominio base de órdenes válidas
        default_domain = [("state", "!=", "draft"), ("state", "!=", "cancel")]
        # Combinar dominio base con el dominio de búsqueda de la UI
        if domain == []:
            real_domain = AND([default_domain])
        else:
            real_domain = AND([domain, default_domain])

        # Permitir acceso a todas las compañías habilitadas para el usuario
        orders_env = self.with_context(allowed_company_ids=self.env.user.company_ids.ids)
        # Buscar órdenes con el dominio expandido
        orders = orders_env.search(real_domain, limit=limit, offset=offset)

        # Buscar líneas de órdenes relacionadas con devoluciones
        orderlines = self.env["pos.order.line"].with_context(
            allowed_company_ids=self.env.user.company_ids.ids
        ).search(
            [
                "|",
                ("refunded_orderline_id.order_id", "in", orders.ids),
                ("order_id", "in", orders.ids),
            ]
        )

        # Construir el mapa de última modificación por orden
        orders_info = defaultdict(lambda: datetime.min)
        for orderline in orderlines:
            # Determinar la orden base de la línea o su orden reembolsada
            if orderline.order_id in orders:
                key_order = orderline.order_id.id
            else:
                key_order = orderline.refunded_orderline_id.order_id.id
            # Actualizar la fecha de última modificación
            if orders_info[key_order] < orderline.write_date:
                orders_info[key_order] = orderline.write_date

        # Calcular el total de resultados sin el límite
        total_count = orders_env.search_count(real_domain)

        # Retornar la información esperada por el POS
        return {"ordersInfo": list(orders_info.items())[::-1], "totalCount": total_count}

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
