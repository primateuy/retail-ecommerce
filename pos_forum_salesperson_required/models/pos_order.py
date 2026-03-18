# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    order_salesperson_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Order Salesperson",
        help="Vendedor asignado a nivel de orden en el POS.",
    )

    def _order_fields(self, ui_order):
        """
        Incluye el vendedor de la orden recibido desde el POS en la creación.

        Args:
            ui_order (dict): Datos de la orden enviados desde el frontend.

        Returns:
            dict: Valores listos para crear la orden en el backend.
        """
        # Obtener los valores base desde la lógica estándar
        result = super()._order_fields(ui_order)
        # Inyectar el vendedor de la orden si viene en el payload
        result["order_salesperson_id"] = ui_order.get("order_salesperson_id") or False
        # Retornar el diccionario completo
        return result

    def _export_for_ui(self, order):
        """
        Expone el vendedor de la orden para sincronización con el POS.

        Args:
            order (pos.order): Orden a exportar.

        Returns:
            dict: Datos exportados para la UI del POS.
        """
        # Obtener los datos base de exportación
        result = super()._export_for_ui(order)
        # Agregar el vendedor de la orden para el frontend
        result["order_salesperson_id"] = (
            order.order_salesperson_id.id if order.order_salesperson_id else False
        )
        # Retornar el resultado final
        return result


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    @api.model_create_multi
    def create(self, vals_list):
        """
        Asigna vendedor de la orden a líneas sin vendedor.

        Args:
            vals_list (list[dict]): Lista de diccionarios de valores para crear líneas.

        Returns:
            recordset: Líneas creadas.
        """
        # Completar vendedor desde la orden si no fue enviado en la línea
        for vals in vals_list:
            if vals.get("order_id") and not vals.get("user_id"):
                order = self.env["pos.order"].browse(vals["order_id"])
                if order.order_salesperson_id:
                    vals["user_id"] = order.order_salesperson_id.id
        # Crear las líneas usando la lógica estándar
        return super().create(vals_list)
