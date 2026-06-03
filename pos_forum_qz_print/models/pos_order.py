# -*- coding: utf-8 -*-

import logging
import re

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _sanitize_pos_html_remove_odoo_web_assets(html_str):
    """
    Quita <link> y <script> que apuntan a /web/assets/ del HTML de reportes QWeb.

    QZ Tray y contextos sin sesión web suelen recibir 404 en esas URLs (hash de
    assets distinto o sin autenticación); el contenido del cupón sigue imprimiéndose.
    """
    if not html_str:
        return html_str
    out = re.sub(
        r'<link[^>]+href=[\'"][^\'"]*?/web/assets/[^\'"]+[\'"][^>]*/?>',
        "",
        html_str,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r'<script[^>]+src=[\'"][^\'"]*?/web/assets/[^\'"]+[\'"][^>]*>\s*</script>',
        "",
        out,
        flags=re.IGNORECASE,
    )
    return out


class PosOrder(models.Model):
    """
    Métodos de apoyo para imprimir el ticket de cambio como HTML (QWeb) desde el POS.

    El HTML se usa con QZ Tray (módulo pos_forum_qz_print) o puede reutilizarse
    con otros clientes que impriman en el navegador.
    """

    _inherit = "pos.order"

    @api.model
    def get_change_ticket_html_for_pos_print(self, order_id, report_action_id):
        """
        Devuelve el HTML del reporte de ticket de cambio para imprimirlo desde el POS.

        :param int order_id: ID de ``pos.order`` en el servidor.
        :param int report_action_id: ID de ``ir.actions.report`` (p. ej. el de
            ``change_ticket_report_id`` en la configuración del POS).
        :return str: documento HTML renderizado por QWeb.
        """
        # Bloque: trazabilidad en logs del servidor (útil con QZ / depuración POS).
        _logger.info(
            "pos_forum_qz_print: solicitud HTML ticket de cambio | order_id=%s | "
            "report_action_id=%s | usuario=%s",
            order_id,
            report_action_id,
            self.env.user.login,
        )

        # Bloque: validar orden según reglas del usuario POS.
        order = self.browse(order_id)
        if not order.exists():
            _logger.warning(
                "pos_forum_qz_print: orden inexistente o sin acceso | order_id=%s",
                order_id,
            )
            raise UserError(_("No se encontró el pedido del punto de venta."))

        # Bloque: validar reporte y modelo destino.
        report = self.env["ir.actions.report"].browse(report_action_id)
        if not report.exists():
            _logger.warning(
                "pos_forum_qz_print: reporte ir.actions.report inexistente | id=%s",
                report_action_id,
            )
            raise UserError(_("No se encontró el reporte solicitado."))
        if report.model != "pos.order":
            _logger.warning(
                "pos_forum_qz_print: reporte no es de pos.order | id=%s model=%s",
                report_action_id,
                report.model,
            )
            raise UserError(_("El reporte indicado no es válido para pedidos POS."))

        # Bloque: mismo render que la vista HTML/PDF del reporte.
        html_result, _mime = self.env["ir.actions.report"]._render_qweb_html(
            report.report_name, order.ids
        )
        if isinstance(html_result, bytes):
            html_str = html_result.decode("utf-8")
        else:
            html_str = str(html_result)
        _logger.info(
            "pos_forum_qz_print: HTML ticket de cambio generado OK | order=%s | "
            "report_name=%s | tamaño_html=%s caracteres",
            order.display_name,
            report.report_name,
            len(html_str),
        )
        return html_str

    @api.model
    def get_loyalty_coupon_code_print_data(self, order_id, loyalty_card_ids=None):
        """
        Devuelve datos para imprimir el reporte «Código de cupón» (loyalty.card)
        de las tarjetas/cupones generados por la orden POS (programas de lealtad
        distintos de gift_card y ewallet).

        Requiere el módulo ``pos_loyalty`` (loyalty.card con source_pos_order_id).

        :param int order_id: ID de ``pos.order``.
        :param list loyalty_card_ids: ids opcionales enviados por el POS (claves de
            ``couponPointChanges`` en el cliente). No aplica puntos; solo selecciona
            tarjetas ya existentes en el servidor, validando que el cliente coincida
            con la orden (para promociones que no enlazan ``source_pos_order_id``).
        Returns:
            dict: ``{'card_ids': [int, ...], 'report_xml_id': str}`` o ``{}`` si no aplica.
        """
        order = self.browse(order_id)
        if not order.exists():
            _logger.warning(
                "pos_forum_qz_print: get_loyalty_coupon_code_print_data | orden inexistente id=%s",
                order_id,
            )
            return {}
        CardModel = self.env["loyalty.card"]
        if "source_pos_order_id" not in CardModel._fields:
            _logger.info(
                "pos_forum_qz_print: pos_loyalty no instalado; sin source_pos_order_id en loyalty.card"
            )
            return {}
        Card = CardModel.sudo()
        # Bloque: cupones creados en esta orden (promociones que emiten tarjeta nueva).
        cards = Card.search([("source_pos_order_id", "=", order.id)])
        # Bloque: cupones aplicados en líneas de recompensa (reward) de la misma orden.
        if "coupon_id" in self.env["pos.order.line"]._fields:
            line_coupons = order.lines.mapped("coupon_id").filtered(lambda c: bool(c))
            cards |= line_coupons
        # Bloque: tarjetas indicadas por el POS (mismo criterio que las claves de
        # coupon_point_changes en el cliente; sin tocar puntos en el servidor).
        partner = order.partner_id
        if loyalty_card_ids:
            for raw_id in loyalty_card_ids:
                try:
                    cid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                card = Card.browse(cid)
                if not card.exists():
                    continue
                if partner and card.partner_id != partner:
                    continue
                if not partner and card.partner_id:
                    continue
                cards |= card
        cards = cards.sudo()

        # Bloque: log detallado de candidatos antes de filtrar.
        if cards:
            candidatos_str = ", ".join(
                "card_id=%s program='%s' program_type='%s'" % (
                    c.id,
                    c.program_id.name if c.program_id else '(sin programa)',
                    c.program_id.program_type if c.program_id else '(sin tipo)',
                )
                for c in cards
            )
            _logger.info(
                "pos_forum_qz_print: candidatos a cupón antes de filtrar | "
                "orden=%s (id=%s) | total=%s | %s",
                order.display_name, order.id, len(cards), candidatos_str,
            )
        else:
            _logger.info(
                "pos_forum_qz_print: sin candidatos a cupón (no hay loyalty.card "
                "vinculadas a la orden) | orden=%s (id=%s)",
                order.display_name, order.id,
            )

        # Bloque: imprimir solo los cupones que sirven para una próxima compra.
        cards = cards.filtered(
            lambda c: c.program_id
            and c.program_id.applies_on == "future"
            and c.program_id.program_type not in ("gift_card", "ewallet")
        )

        # Códigos de cupones canjeados en esta orden (presentes en líneas de recompensa).
        # Se usan para excluir tarjetas consumidas que llegan en loyalty_card_ids.
        consumed_codes = []
        if "coupon_id" in self.env["pos.order.line"]._fields:
            consumed_codes = [
                c.code
                for c in order.lines.mapped("coupon_id").filtered(bool)
                if c.code
            ]

        # Bloque: fallback por ventana de tiempo (write_date). Cubre source_pos_order_id=NULL
        # y el caso donde Odoo actualiza una tarjeta existente en lugar de crear una nueva
        # (el socio ya tiene un cupón pendiente del mismo programa). Se ejecuta DESPUÉS del
        # filtro para no bloquearse por tarjetas de otros tipos (loyalty/both) que llegan
        # en loyalty_card_ids desde el cliente.
            cards = Card.sudo().search([
                ("earned_partner_id", "=", order.partner_id.id),
                ("program_id.applies_on", "=", "future"),
                ("program_id.program_type", "not in", ["gift_card", "ewallet"]),
                ("code", "not in", consumed_codes),
                ("points", ">", 0),
                ("source_pos_order_id", "=", order.id),
            ], order="id desc", limit=10)

        if not cards:
            _logger.info(
                "pos_forum_qz_print: sin cupón de próxima compra para orden %s "
                "(id=%s); ningún candidato cumplió applies_on='future' y "
                "program_type fuera de gift_card/ewallet",
                order.display_name,
                order.id,
            )
            return {}

        # Bloque: log de cupones que pasaron el filtro y se van a imprimir.
        seleccionadas_str = ", ".join(
            "card_id=%s program='%s'" % (
                c.id, c.program_id.name if c.program_id else '?'
            )
            for c in cards
        )
        _logger.info(
            "pos_forum_qz_print: imprimiendo cupón(es) de próxima compra | "
            "orden=%s (id=%s) | total=%s | %s",
            order.display_name, order.id, len(cards), seleccionadas_str,
        )
        # Reporte: copia de loyalty.loyalty_report + marco tipo ticket de cambio (QWeb en XML).
        report = self.env.ref(
            "pos_forum_qz_print.report_loyalty_card_pos_thermal", raise_if_not_found=False
        )
        if not report:
            _logger.warning("pos_forum_qz_print: no se encontró report_loyalty_card_pos_thermal")
            return {}
        xml_id = "pos_forum_qz_print.report_loyalty_card_pos_thermal"
        try:
            data = self.env["ir.model.data"].sudo().search_read(
                [("model", "=", "ir.actions.report"), ("res_id", "=", report.id)],
                ["module", "name"],
                limit=1,
            )
            if data:
                xml_id = f"{data[0]['module']}.{data[0]['name']}"
        except Exception as err:
            _logger.debug("pos_forum_qz_print: fallback xml_id loyalty report: %s", err)
        return {
            "card_ids": cards.ids,
            "report_xml_id": xml_id,
        }

    @api.model
    def get_loyalty_coupon_html_for_pos_print(self, order_id, loyalty_card_ids=None):
        """
        Renderiza el mismo QWeb que el PDF «Código de cupón» para impresión HTML (QZ).

        :param int order_id: ID de ``pos.order``.
        :param list loyalty_card_ids: ids opcionales desde el POS (ver ``get_loyalty_coupon_code_print_data``).
        Returns:
            str: HTML o cadena vacía si no hay cupones aplicables.
        """
        data = self.get_loyalty_coupon_code_print_data(order_id, loyalty_card_ids=loyalty_card_ids)
        if not data.get("card_ids"):
            return ""
        report = self.env.ref(
            "pos_forum_qz_print.report_loyalty_card_pos_thermal", raise_if_not_found=False
        )
        if not report:
            return ""
        html_result, _mime = self.env["ir.actions.report"].sudo()._render_qweb_html(
            report.report_name, data["card_ids"]
        )
        raw = html_result.decode("utf-8") if isinstance(html_result, bytes) else str(html_result)
        return _sanitize_pos_html_remove_odoo_web_assets(raw)
