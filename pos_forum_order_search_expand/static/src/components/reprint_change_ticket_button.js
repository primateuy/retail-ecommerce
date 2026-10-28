/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { Component } from "@odoo/owl";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { useAsyncLockedMethod } from "@point_of_sale/app/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";

export class ReprintChangeTicketButton extends Component {
    static template = "pos_forum_order_search_expand.ReprintChangeTicketButton";

    setup() {
        // Obtener servicios del POS para impresión y acceso a datos
        this.pos = usePos();
        this.report = useService("report");
        this.popup = useService("popup");
        this.click = useAsyncLockedMethod(this.click);
    }

    async click() {
        // Validar orden seleccionada
        const order = this.props.order;
        if (!order) {
            return;
        }

        // Validar que exista reporte configurado
        const reportValue = this.pos.config.change_ticket_report_id;
        if (!reportValue) {
            this.popup.add(ErrorPopup, {
                title: _t("Change Ticket"),
                body: _t("No change ticket report is configured for this POS."),
            });
            return;
        }

        // Obtener ID de la orden en el backend
        const orderId = this._getOrderBackendId(order);
        if (!orderId) {
            this.popup.add(ErrorPopup, {
                title: _t("Change Ticket"),
                body: _t("The order is not available for reprinting."),
            });
            return;
        }

        // Pasar el id numérico del reporte tal cual: el servicio `report` del POS
        // lo resuelve contra /web/action/load, que acepta un id entero y lee la
        // acción con sudo(). Traducirlo antes a XML ID obligaba a leer
        // ir.model.data, cuya ACL es solo de Administración / Permisos de acceso,
        // y al cajero le saltaba un "Error de acceso" al reimprimir.
        const reportId = Array.isArray(reportValue) ? reportValue[0] : reportValue;
        await this.report.doAction(reportId, [orderId]);
    }

    _getOrderBackendId(order) {
        // Priorizar IDs de backend si existen
        return order.backendId || order.server_id || order.id || false;
    }
}
