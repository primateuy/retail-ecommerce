# -*- coding: utf-8 -*-
import json
import logging
import time

import requests

from odoo import models

_logger = logging.getLogger(__name__)

_RETRY_DELAYS = (1, 2, 4)  # segundos entre reintentos


class FenicioApiError(Exception):
    """Error retornado por la API de Fenicio (error=true en el cuerpo)."""
    def __init__(self, message, response_body=None):
        super().__init__(message)
        self.response_body = response_body


class FenicioClient(models.AbstractModel):
    _name = "fenicio.client"
    _description = "Cliente HTTP para la API v1 de Fenicio (outbound)"

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def _get_base_url(self):
        url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("fenicio_integration.base_url", default="")
            .rstrip("/")
        )
        if not url:
            raise ValueError(
                "Parámetro 'fenicio_integration.base_url' no configurado. "
                "Ingresalo en Ajustes → Parámetros técnicos."
            )
        return url

    def _get_timeout(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("fenicio_integration.timeout_seconds", default="30")
        )
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 30

    # ------------------------------------------------------------------
    # Logging a fenicio.log
    # ------------------------------------------------------------------

    def _log(self, estado, endpoint, request_data=None, response_data=None):
        try:
            self.env["fenicio.log"].registrar(
                estado=estado,
                endpoint=endpoint,
                request=json.dumps(request_data, ensure_ascii=False) if request_data else None,
                mensaje=json.dumps(response_data, ensure_ascii=False) if response_data else None,
            )
        except Exception as e:
            _logger.warning("Fenicio: no se pudo registrar en fenicio.log: %s", e)

    # ------------------------------------------------------------------
    # Método central de request con reintentos
    # ------------------------------------------------------------------

    def _request(self, method, path, *, params=None, data=None, retries=3):
        """
        Realiza una llamada HTTP a la API v1 de Fenicio.

        La API usa IP whitelist como único mecanismo de autenticación;
        no se envían headers de autorización. Los POST usan
        application/x-www-form-urlencoded según la documentación oficial.

        Retorna el dict JSON si error=false.
        Lanza FenicioApiError si el cuerpo indica error=true.
        Lanza requests.RequestException ante fallos de red/timeout (tras reintentos).
        """
        base_url = self._get_base_url()
        url = f"{base_url}/{path.lstrip('/')}"
        timeout = self._get_timeout()
        delays = _RETRY_DELAYS[:retries]
        last_exc = None

        request_data = {"method": method, "url": url, "params": params, "data": data}

        for attempt, delay in enumerate(delays + [None], start=1):
            try:
                _logger.debug(
                    "Fenicio %s %s | intento=%d params=%s data=%s",
                    method, url, attempt, params, data,
                )
                response = requests.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    timeout=timeout,
                )
                response.raise_for_status()
                body = response.json()
                _logger.debug("Fenicio respuesta: %s", body)

                if body.get("error"):
                    self._log("error", path, request_data=request_data, response_data=body)
                    raise FenicioApiError(
                        body.get("msj") or "Error sin mensaje", response_body=body
                    )

                self._log("ok", path, request_data=request_data, response_data=body)
                return body

            except FenicioApiError:
                raise

            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                _logger.warning(
                    "Fenicio %s %s | intento=%d/%d falló: %s",
                    method, url, attempt, len(delays) + 1, exc,
                )
                if delay is not None:
                    time.sleep(delay)

            except requests.HTTPError as exc:
                self._log("error", path, request_data=request_data, response_data={"exc": str(exc)})
                _logger.error("Fenicio HTTP error %s %s: %s", method, url, exc)
                raise

        self._log("error", path, request_data=request_data, response_data={"exc": str(last_exc)})
        raise last_exc

    # ------------------------------------------------------------------
    # Endpoints: Órdenes
    # ------------------------------------------------------------------

    def get_orders(
        self,
        page=1,
        page_size=50,
        date_from=None,
        date_to=None,
        estado=None,
        estado_entrega=None,
        cliente=None,
        incluir_atributos=False,
    ):
        """GET /API_V1/ordenes — retorna dict con totAbs y ordenes."""
        params = {"pag": page, "tot": page_size}
        if date_from:
            params["fDesde"] = date_from
        if date_to:
            params["fHasta"] = date_to
        if estado:
            params["estado"] = estado
        if estado_entrega:
            params["estadoEntrega"] = estado_entrega
        if cliente:
            params["cliente"] = cliente
        if incluir_atributos:
            params["incluirAtributosProducto"] = 1
        return self._request("GET", "ordenes", params=params)

    def get_all_orders(self, **kwargs):
        """Iterador que recorre todas las páginas de get_orders."""
        page = 1
        page_size = kwargs.pop("page_size", 50)
        while True:
            result = self.get_orders(page=page, page_size=page_size, **kwargs)
            orders = result.get("ordenes") or []
            yield from orders
            total = result.get("totAbs", 0)
            if page * page_size >= total:
                break
            page += 1

    def get_order(self, id_orden):
        """GET /API_V1/ordenes/{idOrden}"""
        return self._request("GET", f"ordenes/{id_orden}")

    def update_delivery_status(self, id_orden, estado_entrega, codigo_tracking=None, info=None):
        """POST /API_V1/ordenes/{idOrden}/estado-entrega (form-urlencoded)."""
        data = {"estado": estado_entrega}
        if codigo_tracking is not None:
            data["codigoTracking"] = str(codigo_tracking)[:32]
        if info is not None:
            data["info"] = info
        return self._request("POST", f"ordenes/{id_orden}/estado-entrega", data=data)

    # ------------------------------------------------------------------
    # Endpoints: Catálogo
    # ------------------------------------------------------------------

    def get_branches(self):
        """GET /API_V1/sucursales"""
        return self._request("GET", "sucursales")

    def get_shipping_types(self):
        """GET /API_V1/tipos-envio"""
        return self._request("GET", "tipos-envio")
