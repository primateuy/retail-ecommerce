# -*- coding: utf-8 -*-

import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
