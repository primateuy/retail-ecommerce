# -*- coding: utf-8 -*-
import json
import logging

from datetime import datetime, timedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class FenicioSync(models.AbstractModel):
    _name = "fenicio.sync"
    _description = "Servicio de sincronización de órdenes Fenicio (API v1)"

    # ------------------------------------------------------------------
    # Punto de entrada del cron
    # ------------------------------------------------------------------

    @api.model
    def run_cron_sync_orders(self):
        """Sincroniza las órdenes de las últimas 25 horas (1h de overlap)."""
        date_to = fields.Date.today()
        date_from = (datetime.now() - timedelta(hours=25)).date()
        _logger.info("Fenicio sync: órdenes desde %s hasta %s", date_from, date_to)
        try:
            self._sync_orders(date_from=str(date_from), date_to=str(date_to))
        except Exception as e:
            _logger.error("Fenicio sync: error en cron: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Sincronización
    # ------------------------------------------------------------------

    def _sync_orders(self, date_from=None, date_to=None, estado=None, estado_entrega=None):
        """Descarga todas las órdenes del rango y las persiste en Odoo."""
        client = self.env["fenicio.client"]
        kwargs = {}
        if date_from:
            kwargs["date_from"] = date_from
        if date_to:
            kwargs["date_to"] = date_to
        if estado:
            kwargs["estado"] = estado
        if estado_entrega:
            kwargs["estado_entrega"] = estado_entrega

        synced = 0
        errors = 0
        for raw_order in client.get_all_orders(**kwargs):
            try:
                self._update_or_create_order(raw_order)
                synced += 1
            except Exception as e:
                errors += 1
                _logger.error(
                    "Fenicio sync: error procesando orden %s: %s",
                    raw_order.get("idOrden"), e, exc_info=True,
                )
        _logger.info("Fenicio sync: %d órdenes procesadas, %d errores", synced, errors)
        return synced, errors

    def _update_or_create_order(self, raw_order):
        if not raw_order:
            return None
        id_fenicio = raw_order.get("idOrden")
        if not id_fenicio:
            _logger.warning("Fenicio sync: orden sin idOrden, omitida: %s", raw_order)
            return None

        vals = self._map_order_vals(raw_order)
        existing = self.env["fenicio.order"].search([("id_fenicio", "=", id_fenicio)], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.env["fenicio.order"].create(vals)

    # ------------------------------------------------------------------
    # Mapeo API → campos Odoo
    # ------------------------------------------------------------------

    def _map_order_vals(self, raw_order):
        comprador = raw_order.get("comprador") or {}
        pago = raw_order.get("pago") or {}
        entrega = raw_order.get("entrega") or {}
        parse_dt = self.env["fenicio.order"]._parse_datetime

        return {
            "id_fenicio": raw_order.get("idOrden"),
            "numero_orden": raw_order.get("numeroOrden"),
            "referencia": raw_order.get("referencia"),
            "estado": raw_order.get("estado"),
            "estado_entrega": entrega.get("estado"),
            "origen": raw_order.get("origen"),
            "fecha_inicio": parse_dt(raw_order.get("fechaInicio")),
            "fecha_fin": parse_dt(raw_order.get("fechaFin")),
            "fecha_pago": parse_dt(pago.get("fechaPago")),
            "comprador_email": comprador.get("email"),
            "comprador_nombre": (
                f"{comprador.get('nombre', '')} {comprador.get('apellido', '')}".strip()
            ),
            "comprador_telefono": comprador.get("telefono"),
            "moneda": raw_order.get("moneda"),
            "importe_total": raw_order.get("importeTotal") or 0.0,
            "raw_data": json.dumps(raw_order, ensure_ascii=False),
            "last_sync": fields.Datetime.now(),
        }
