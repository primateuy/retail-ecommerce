# -*- coding: utf-8 -*-
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ESTADOS_ENTREGA = [
    ("AGUARDANDO_DESPACHO", "Aguardando despacho"),
    ("EN_CAMINO", "En camino"),
    ("ENTREGADO", "Entregado"),
    ("NO_ENTREGADO", "No entregado"),
    ("DEVUELTO", "Devuelto"),
]


class FenicioDeliveryStatusWizard(models.TransientModel):
    _name = "fenicio.delivery.status.wizard"
    _description = "Cambiar estado de entrega – Fenicio"

    order_id = fields.Many2one("fenicio.order", string="Orden", required=True, readonly=True)
    estado_entrega = fields.Selection(ESTADOS_ENTREGA, string="Nuevo estado de entrega", required=True)
    codigo_tracking = fields.Char(string="Código de tracking", size=32)
    info = fields.Text(string="Información adicional")

    def action_confirm(self):
        self.ensure_one()
        order = self.order_id
        try:
            result = self.env["fenicio.client"].update_delivery_status(
                id_orden=order.id_fenicio,
                estado_entrega=self.estado_entrega,
                codigo_tracking=self.codigo_tracking or None,
                info=self.info or None,
            )
        except Exception as e:
            raise UserError(f"Error al actualizar el estado en Fenicio: {e}") from e

        updated_orden = (result or {}).get("orden") or {}
        if updated_orden:
            self.env["fenicio.sync"]._update_or_create_order(updated_orden)

        _logger.info(
            "Estado de entrega de orden Fenicio #%s actualizado a %s",
            order.id_fenicio, self.estado_entrega,
        )
        return {"type": "ir.actions.act_window_close"}
