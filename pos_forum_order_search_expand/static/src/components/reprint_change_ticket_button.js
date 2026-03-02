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
        this.orm = useService("orm");
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

        // Resolver el XML ID del reporte configurado
        const reportId = Array.isArray(reportValue) ? reportValue[0] : reportValue;
        const reportXmlId = await this._getReportXmlId(reportId);
        if (!reportXmlId) {
            this.popup.add(ErrorPopup, {
                title: _t("Change Ticket"),
                body: _t("Could not resolve the report identifier."),
            });
            return;
        }

        // Ejecutar la impresión mediante el servicio de reportes
        await this.report.doAction(reportXmlId, [orderId]);
    }

    _getOrderBackendId(order) {
        // Priorizar IDs de backend si existen
        return order.backendId || order.server_id || order.id || false;
    }

    async _getReportXmlId(reportId) {
        // Consultar el XML ID del reporte desde ir.model.data
        const modelData = await this.orm.searchRead(
            "ir.model.data",
            [
                ["model", "=", "ir.actions.report"],
                ["res_id", "=", reportId],
            ],
            ["module", "name"],
            { limit: 1 }
        );

        // Construir el XML ID si existe registro
        if (modelData && modelData.length > 0) {
            return `${modelData[0].module}.${modelData[0].name}`;
        }

        // Retornar null si no se encuentra
        return null;
    }
}
