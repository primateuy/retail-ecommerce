# -*- coding: utf-8 -*-

import logging
import re

from odoo import http, _
from odoo.http import request, content_disposition

_logger = logging.getLogger(__name__)


# Bloque: separador de páginas estándar para wkhtmltopdf.
# El recibo OWL no tiene <html>/<head> propios; los reportes QWeb sí. Al
# concatenar varios fragmentos en un único body, agregamos un div con
# page-break-before para que cada documento empiece en una página nueva del PDF.
_PAGE_BREAK = (
    '<div style="page-break-before: always; break-before: page;">&nbsp;</div>'
)


def _strip_html_envelope(html_str):
    """
    Devuelve solo el contenido entre <body>...</body>.

    wkhtmltopdf acepta un único documento, así que cuando concatenamos varios
    HTML completos (con <html>, <head>) hay que quedarse con el cuerpo de cada
    uno y montarlos dentro de un único envoltorio común.
    """
    if not html_str:
        return ""
    txt = str(html_str)
    body_match = re.search(
        r"<body[^>]*>([\s\S]*?)</body>", txt, flags=re.IGNORECASE
    )
    if body_match:
        return body_match.group(1)
    return txt


class PosForumQzRoutineDownloadController(http.Controller):
    """
    Endpoint de fallback de la rutina de impresión QZ.

    Cuando QZ Tray no responde y ``pos.config.qz_tray_download_on_failure``
    está activo, el frontend POS hace un POST a este endpoint con el HTML del
    recibo y el id del ``pos.order``. El servidor renderiza los reportes que
    apliquen (ticket de cambio, voucher OCA, cupón de próxima compra), los
    combina con saltos de página y devuelve un único PDF descargable. Esto
    evita el bloqueo del navegador a múltiples descargas consecutivas en el
    mismo evento de usuario.
    """

    @http.route(
        "/pos_forum_qz_print/download_routine_pdf",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def download_routine_pdf(self, **post):
        try:
            order_id_raw = post.get("order_id")
            receipt_html = post.get("receipt_html") or ""
            loyalty_card_ids_raw = post.get("loyalty_card_ids") or ""
            order_id = int(order_id_raw) if order_id_raw else 0
            if not order_id:
                _logger.warning(
                    "pos_forum_qz_print: routine pdf | order_id ausente o inválido (%r).",
                    order_id_raw,
                )
                return request.make_response(
                    "order_id requerido",
                    headers=[("Content-Type", "text/plain; charset=utf-8")],
                    status=400,
                )

            order = request.env["pos.order"].browse(order_id)
            if not order.exists():
                _logger.warning(
                    "pos_forum_qz_print: routine pdf | orden inexistente id=%s",
                    order_id,
                )
                return request.make_response(
                    "Orden no encontrada",
                    headers=[("Content-Type", "text/plain; charset=utf-8")],
                    status=404,
                )

            # Bloque: ids de loyalty.card seleccionados desde el POS (mismas
            # claves que ``couponPointChanges`` en el cliente).
            loyalty_card_ids = []
            for token in str(loyalty_card_ids_raw).split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    loyalty_card_ids.append(int(token))
                except ValueError:
                    continue

            cfg = order.config_id
            change_ticket_html = ""
            if cfg.change_ticket_report_id:
                try:
                    change_ticket_html = request.env["pos.order"].sudo().get_change_ticket_html_for_pos_print(
                        order.id, cfg.change_ticket_report_id.id
                    )
                except Exception:
                    _logger.exception(
                        "pos_forum_qz_print: routine pdf | error obteniendo HTML del ticket de cambio."
                    )

            voucher_html = ""
            try:
                voucher_html = request.env["pos.order"].sudo().get_oca_voucher_html_for_pos_print(
                    order.id, raise_on_missing=False
                ) or ""
            except TypeError:
                # Bloque: compatibilidad si el método no acepta raise_on_missing.
                try:
                    voucher_html = request.env["pos.order"].sudo().get_oca_voucher_html_for_pos_print(
                        order.id
                    ) or ""
                except Exception:
                    voucher_html = ""
            except Exception:
                voucher_html = ""

            coupon_html = ""
            try:
                coupon_html = request.env["pos.order"].sudo().get_loyalty_coupon_html_for_pos_print(
                    order.id, loyalty_card_ids=loyalty_card_ids
                ) or ""
            except Exception:
                _logger.exception(
                    "pos_forum_qz_print: routine pdf | error obteniendo HTML del cupón de próxima compra."
                )

            # Bloque: armar lista ordenada de fragmentos (recibo, ticket de cambio,
            # voucher OCA, cupón próxima compra). Solo se incluyen los que tienen
            # contenido — voucher y cupón pueden no aplicar.
            fragments = []
            etiquetas = []
            if receipt_html and receipt_html.strip():
                fragments.append(_strip_html_envelope(receipt_html))
                etiquetas.append("recibo")
            if change_ticket_html and str(change_ticket_html).strip():
                fragments.append(_strip_html_envelope(change_ticket_html))
                etiquetas.append("ticket de cambio")
            if voucher_html and str(voucher_html).strip():
                fragments.append(_strip_html_envelope(voucher_html))
                etiquetas.append("voucher OCA")
            if coupon_html and str(coupon_html).strip():
                fragments.append(_strip_html_envelope(coupon_html))
                etiquetas.append("cupón próxima compra")

            if not fragments:
                _logger.warning(
                    "pos_forum_qz_print: routine pdf | no hay fragmentos HTML para combinar."
                )
                return request.make_response(
                    "Nada para imprimir",
                    headers=[("Content-Type", "text/plain; charset=utf-8")],
                    status=204,
                )

            base_href = request.httprequest.host_url.rstrip("/")
            combined_body = _PAGE_BREAK.join(fragments)
            combined_html = (
                "<!DOCTYPE html>"
                '<html><head><meta charset="utf-8"/>'
                f'<base href="{base_href}/"/>'
                "<style>"
                "body { margin: 0; padding: 0; font-family: sans-serif; }"
                # Los fragmentos vienen con el ancho clavado en milímetros
                # (max-width: 80mm) y centrados. Sobre el área imprimible real
                # del rollo eso desborda; se deja que ocupen la página.
                ".container, .container-fluid, .article, .page,"
                ".o_forum_loyalty_coupon_thermal, .oca-thermal-voucher {"
                "  width: 100% !important; max-width: 100% !important;"
                "  margin-left: 0 !important; margin-right: 0 !important;"
                "  padding-left: 0 !important; padding-right: 0 !important;"
                "}"
                "img { max-width: 100% !important; }"
                "@media print {"
                "  div[style*='page-break-before'] { page-break-before: always; }"
                "}"
                "</style>"
                f"</head><body>{combined_body}</body></html>"
            )

            _logger.info(
                "pos_forum_qz_print: routine pdf | orden=%s | fragmentos=%s | total_html=%s caracteres",
                order.display_name,
                ", ".join(etiquetas),
                len(combined_html),
            )

            order_ref = re.sub(
                r"[^A-Za-z0-9_-]+",
                "_",
                order.pos_reference or order.name or f"POS_{order.id}",
            )

            # Bloque: estado del binario wkhtmltopdf. Si no está instalado /
            # roto, no tiene sentido invocarlo: devolvemos el HTML combinado
            # como descarga para que el operador igual pueda imprimirlo desde
            # el navegador (Cmd+P / Ctrl+P → Guardar como PDF).
            ReportModel = request.env["ir.actions.report"].sudo()
            wkhtmltopdf_state = "ok"
            try:
                # 🔴 En 17.0 el método se llama ``get_wkhtmltopdf_state`` (sin guion
                # bajo); el nombre con guion es el de 16.0. Llamar al viejo levantaba
                # AttributeError, lo comía este mismo ``except`` y el estado quedaba
                # en 'broken': el respaldo de la rutina NUNCA devolvió un PDF, siempre
                # el HTML combinado. Y un HTML impreso desde el navegador sale con los
                # márgenes A4 que trae el diálogo de impresión.
                if hasattr(ReportModel, "get_wkhtmltopdf_state"):
                    wkhtmltopdf_state = ReportModel.get_wkhtmltopdf_state()
                else:
                    wkhtmltopdf_state = ReportModel._get_wkhtmltopdf_state()
            except Exception:
                _logger.exception(
                    "pos_forum_qz_print: routine pdf | no se pudo consultar el estado de wkhtmltopdf."
                )
                wkhtmltopdf_state = "broken"

            pdf_bytes = None
            if wkhtmltopdf_state == "ok":
                # Bloque: usar wkhtmltopdf con el cuerpo HTML combinado. Pasamos
                # un único elemento en la lista de bodies; los page-break del
                # propio HTML separan los documentos en páginas distintas.
                #
                # ``report_ref`` no es decorativo: sin él, _run_wkhtmltopdf cae en
                # ``self.get_paperformat()`` sobre un recordset vacío, que devuelve
                # el formato de la compañía (A4, márgenes 40/32/7/7). Toda la rutina
                # se maquetaba sobre 210 mm y después se imprimía en el rollo de
                # 80 mm: de ahí los márgenes mal y el recorte a los costados.
                try:
                    pdf_bytes = ReportModel._run_wkhtmltopdf(
                        [combined_html],
                        report_ref="pos_forum_qz_print.report_loyalty_card_pos_thermal",
                    )
                except FileNotFoundError:
                    _logger.warning(
                        "pos_forum_qz_print: routine pdf | wkhtmltopdf no encontrado en PATH; "
                        "se devuelve HTML combinado como fallback."
                    )
                    pdf_bytes = None
                except Exception:
                    _logger.exception(
                        "pos_forum_qz_print: routine pdf | _run_wkhtmltopdf falló; "
                        "se devuelve HTML combinado como fallback."
                    )
                    pdf_bytes = None
            else:
                _logger.warning(
                    "pos_forum_qz_print: routine pdf | wkhtmltopdf state=%s "
                    "(no instalado o no operativo); se devuelve HTML combinado.",
                    wkhtmltopdf_state,
                )

            if pdf_bytes:
                filename = f"Rutina_{order_ref}.pdf"
                return request.make_response(
                    pdf_bytes,
                    headers=[
                        ("Content-Type", "application/pdf"),
                        ("Content-Length", str(len(pdf_bytes))),
                        ("Content-Disposition", content_disposition(filename)),
                    ],
                )

            # Bloque: fallback HTML. Mismo documento concatenado, pero servido
            # como ``.html`` con ``attachment`` para que el navegador lo guarde
            # en disco. El operador puede abrirlo e imprimirlo manualmente.
            html_payload = combined_html.encode("utf-8")
            filename = f"Rutina_{order_ref}.html"
            return request.make_response(
                html_payload,
                headers=[
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(html_payload))),
                    ("Content-Disposition", content_disposition(filename)),
                ],
            )
        except Exception:
            _logger.exception(
                "pos_forum_qz_print: routine pdf | error inesperado generando descarga."
            )
            return request.make_response(
                _("Error generando PDF de rutina."),
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=500,
            )
