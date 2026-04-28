# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.odoo_fenicio.models.fenicio_client import FenicioApiError


class TestFenicioClient(TransactionCase):

    def setUp(self):
        super().setUp()
        self.client = self.env["fenicio.client"]
        self.env["ir.config_parameter"].sudo().set_param(
            "fenicio_integration.base_url", "https://test.fenicio.com/API_V1"
        )

    # ------------------------------------------------------------------

    def test_get_base_url_strips_trailing_slash(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "fenicio_integration.base_url", "https://test.fenicio.com/API_V1/"
        )
        self.assertEqual(self.client._get_base_url(), "https://test.fenicio.com/API_V1")

    def test_get_base_url_raises_when_not_configured(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "fenicio_integration.base_url", ""
        )
        with self.assertRaises(ValueError):
            self.client._get_base_url()

    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.requests.request")
    def test_request_returns_body_on_success(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": False, "msj": "", "ordenes": []}
        mock_request.return_value = mock_resp

        result = self.client._request("GET", "ordenes")
        self.assertFalse(result["error"])

    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.requests.request")
    def test_request_raises_fenicio_api_error(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": True, "msj": "Orden no encontrada"}
        mock_request.return_value = mock_resp

        with self.assertRaises(FenicioApiError) as ctx:
            self.client._request("GET", "ordenes/999")
        self.assertIn("Orden no encontrada", str(ctx.exception))

    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.time.sleep")
    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.requests.request")
    def test_request_retries_on_timeout(self, mock_request, mock_sleep):
        import requests as _requests
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": False, "msj": "", "ordenes": []}
        mock_request.side_effect = [_requests.Timeout("timeout"), mock_resp]

        result = self.client._request("GET", "ordenes", retries=2)
        self.assertEqual(mock_request.call_count, 2)
        self.assertFalse(result["error"])

    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.time.sleep")
    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.requests.request")
    def test_request_raises_after_all_retries_exhausted(self, mock_request, mock_sleep):
        import requests as _requests
        mock_request.side_effect = _requests.Timeout("timeout persistente")

        with self.assertRaises(_requests.Timeout):
            self.client._request("GET", "ordenes", retries=2)
        self.assertEqual(mock_request.call_count, 2)

    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.requests.request")
    def test_get_orders_sends_pagination_params(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": False, "msj": "", "totAbs": 0, "ordenes": []}
        mock_request.return_value = mock_resp

        self.client.get_orders(page=2, page_size=100, estado="PENDIENTE")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["params"]["pag"], 2)
        self.assertEqual(kwargs["params"]["tot"], 100)
        self.assertEqual(kwargs["params"]["estado"], "PENDIENTE")

    @patch("odoo.addons.odoo_fenicio.models.fenicio_client.requests.request")
    def test_update_delivery_status_posts_form_data(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": False, "msj": "", "orden": {}}
        mock_request.return_value = mock_resp

        self.client.update_delivery_status(
            id_orden=35,
            estado_entrega="AGUARDANDO_DESPACHO",
            codigo_tracking="TRK123",
            info="En depósito",
        )
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["estado"], "AGUARDANDO_DESPACHO")
        self.assertEqual(kwargs["data"]["codigoTracking"], "TRK123")
        self.assertEqual(kwargs["data"]["info"], "En depósito")
