# -*- coding: utf-8 -*-

import base64
import json
import logging
from pathlib import Path

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class QzSignController(http.Controller):
    """
    Endpoint de firma para QZ Tray.

    Firma el `data` recibido desde el frontend usando la llave privada del servidor
    y devuelve la firma en base64.
    """

    @staticmethod
    def _private_key_path():
        # Bloque: ruta local del módulo, fuera de static para evitar exposición pública.
        return Path(__file__).resolve().parents[1] / "keys" / "private-key.pem"

    @staticmethod
    def _sign_payload(data_to_sign):
        # Bloque: importar cryptography de forma diferida para reportar error claro.
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except Exception as exc:
            raise RuntimeError(
                "Falta la librería 'cryptography' en el entorno Python de Odoo."
            ) from exc

        # Bloque: cargar llave privada PEM.
        key_file = QzSignController._private_key_path()
        if not key_file.exists():
            raise FileNotFoundError(f"No existe la llave privada en {key_file}")
        private_key = serialization.load_pem_private_key(
            key_file.read_bytes(),
            password=None,
        )

        # Bloque: firmar contenido para QZ y devolver base64.
        # Bloque: compatibilidad con qz-tray.js legado (sin setSignatureAlgorithm).
        # Esta variante valida firmas estilo SHA1withRSA.
        signature = private_key.sign(
            data_to_sign.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        return base64.b64encode(signature).decode("ascii")

    @http.route(
        "/pos_forum_qz_print/sign",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def sign_qz_payload(self, **kwargs):
        """
        Firma payload de QZ recibido como JSON: {"data": "..."}.
        """
        try:
            # Bloque: parseo robusto del body JSON.
            body = request.httprequest.data or b"{}"
            payload = json.loads(body.decode("utf-8"))
            data_to_sign = payload.get("data")
            if not data_to_sign:
                return request.make_response(
                    "Missing 'data' field",
                    headers=[("Content-Type", "text/plain; charset=utf-8")],
                    status=400,
                )

            # Bloque: firma y respuesta de texto plano.
            signature_b64 = self._sign_payload(data_to_sign)
            return request.make_response(
                signature_b64,
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=200,
            )
        except Exception:
            _logger.exception("Error firmando payload para QZ Tray.")
            return request.make_response(
                "Unable to sign payload",
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=500,
            )
