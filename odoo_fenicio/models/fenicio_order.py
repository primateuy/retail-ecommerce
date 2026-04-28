# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FenicioOrder(models.Model):
    _name = "fenicio.order"
    _description = "Orden de Fenicio (API v1)"
    _order = "fecha_inicio desc"
    _rec_name = "numero_orden"

    id_fenicio = fields.Integer(string="ID Fenicio", readonly=True, index=True)
    numero_orden = fields.Char(string="Número de orden", readonly=True)
    referencia = fields.Char(string="Referencia", readonly=True)
    estado = fields.Char(string="Estado", readonly=True)
    estado_entrega = fields.Char(string="Estado de entrega", readonly=True)
    origen = fields.Char(string="Origen", readonly=True)

    fecha_inicio = fields.Datetime(string="Fecha de inicio", readonly=True)
    fecha_fin = fields.Datetime(string="Fecha de fin", readonly=True)
    fecha_pago = fields.Datetime(string="Fecha de pago", readonly=True)

    comprador_email = fields.Char(string="Email comprador", readonly=True)
    comprador_nombre = fields.Char(string="Nombre comprador", readonly=True)
    comprador_telefono = fields.Char(string="Teléfono comprador", readonly=True)

    moneda = fields.Char(string="Moneda", readonly=True)
    importe_total = fields.Float(string="Importe total", readonly=True, digits=(10, 2))

    raw_data = fields.Text(string="Datos raw (JSON)", readonly=True)
    last_sync = fields.Datetime(string="Última sincronización", readonly=True)

    def action_refresh(self):
        self.ensure_one()
        try:
            result = self.env["fenicio.client"].get_order(self.id_fenicio)
        except Exception as e:
            raise UserError(f"No se pudo actualizar la orden desde Fenicio: {e}") from e
        self.env["fenicio.sync"]._update_or_create_order(result.get("orden") or {})

    def action_update_delivery_status(self):
        return {
            "name": "Cambiar estado de entrega",
            "type": "ir.actions.act_window",
            "res_model": "fenicio.delivery.status.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    @api.model
    def _parse_datetime(self, value):
        if not value:
            return False
        try:
            return fields.Datetime.from_string(value.replace("T", " ")[:19])
        except Exception:
            return False
