/** @odoo-module */

import {patch} from "@web/core/utils/patch";
import {ReceiptScreen} from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import {useService} from "@web/core/utils/hooks";
import {onMounted, onWillUnmount} from "@odoo/owl";

/**
 * Ticket de cambio Fiserv, rutina, voucher ITD y cupón lealtad.
 * Solo muestra la fila si hay fiserv_change_ticket_report_id (no usa el reporte OCA
 * para evitar duplicar botones cuando OCA y Fiserv están instalados).
 */
patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.report = useService("report");

        onMounted(() => {
            setTimeout(() => {
                this._addFiservChangeTicketRowSafely();
            }, 500);
        });

        onWillUnmount(() => {
            this._removeFiservChangeTicketRow();
        });
    },

    /**
     * Solo reporte Fiserv: OCA tiene su propia fila en su módulo.
     */
    _fiservHasChangeTicketReportConfigured() {
        const c = this.pos.config;
        return Boolean(c.fiserv_change_ticket_report_id);
    },

    _addFiservChangeTicketRowSafely() {
        if (!this._fiservHasChangeTicketReportConfigured()) {
            return;
        }
        if (document.querySelector(".fiserv-change-ticket-actions-row")) {
            return;
        }

        const screenContent =
            this.el?.querySelector(".screen-content") ||
            document.querySelector(".receipt-screen .screen-content");
        if (!screenContent) {
            return;
        }

        const actionsArea = screenContent.querySelector(".actions");
        if (!actionsArea) {
            return;
        }

        const printButtonContainer = actionsArea.querySelector(".buttons");
        const newButtonContainer = document.createElement("div");
        newButtonContainer.className = "fiserv-change-ticket-container mt-2 w-100";
        newButtonContainer.style.marginTop = "0.5rem";

        const row = document.createElement("div");
        row.className =
            "fiserv-change-ticket-actions-row d-flex flex-wrap justify-content-stretch w-100";
        row.style.gap = "0.5rem";

        const mkBtn = (label, title, iconClass, handler) => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "btn btn-secondary btn-sm flex-fill";
            b.style.minWidth = "4.75rem";
            b.style.flex = "1 1 22%";
            b.style.maxWidth = "none";
            b.style.padding = "0.5rem 0.4rem";
            b.style.lineHeight = "1.2";
            b.title = title;
            b.innerHTML = `
                <span class="d-flex flex-column align-items-center justify-content-center gap-1" style="gap: 0.2rem;">
                    <i class="fa ${iconClass}" style="font-size: 1.05rem; opacity: 0.95;" aria-hidden="true"></i>
                    <strong style="font-weight: 700; font-size: 0.82rem; letter-spacing: 0.02em;">${label}</strong>
                </span>
            `;
            b.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                handler();
            };
            return b;
        };

        row.appendChild(
            mkBtn("Rutina", "Recibo + ticket de cambio + voucher (Fiserv ITD)", "fa-tasks", () =>
                this.fiservPrintChangeTicketRoutine()
            )
        );
        row.appendChild(
            mkBtn("T-Cambio", "Solo ticket de cambio", "fa-exchange", () =>
                this.fiservPrintChangeTicketDocumentOnly()
            )
        );
        row.appendChild(
            mkBtn("Voucher", "Voucher tarjeta Fiserv ITD", "fa-credit-card", () =>
                this.fiservPrintVoucherOnly()
            )
        );
        row.appendChild(
            mkBtn("Cupón PC", "Código de cupón de promoción (lealtad)", "fa-tag", () =>
                this.fiservPrintLoyaltyCouponCode()
            )
        );

        newButtonContainer.appendChild(row);

        if (printButtonContainer) {
            if (printButtonContainer.nextSibling) {
                printButtonContainer.parentNode.insertBefore(
                    newButtonContainer,
                    printButtonContainer.nextSibling
                );
            } else {
                printButtonContainer.parentNode.appendChild(newButtonContainer);
            }
        } else {
            actionsArea.appendChild(newButtonContainer);
        }
    },

    _removeFiservChangeTicketRow() {
        const container = document.querySelector(".fiserv-change-ticket-container");
        if (container) {
            container.remove();
        }
    },

    async _fiservGetBackendOrderIdForChangeTicket() {
        const order = this.pos.get_order();
        if (!order) {
            return null;
        }
        let orderId = order.server_id || order.id;
        if (!orderId) {
            try {
                const orderData = order.export_for_printing();
                if (orderData?.id) {
                    orderId = orderData.id;
                }
            } catch (e) {
                console.warn("odoo_pos_fiserv: export_for_printing sin id:", e);
            }
        }
        if (!orderId && (order.name || order.pos_reference)) {
            try {
                const orderRef = order.name || order.pos_reference;
                const searchResult = await this.orm.searchRead(
                    "pos.order",
                    [
                        "|",
                        ["name", "=", orderRef],
                        ["pos_reference", "=", orderRef],
                    ],
                    ["id"],
                    {limit: 1}
                );
                if (searchResult?.length) {
                    orderId = searchResult[0].id;
                }
            } catch (e) {
                console.warn("odoo_pos_fiserv: búsqueda orden por referencia:", e);
            }
        }
        return orderId || null;
    },

    /**
     * ID del reporte de ticket de cambio Fiserv en pos.config.
     */
    _fiservResolveChangeTicketReportId() {
        const c = this.pos.config;
        const fid = c.fiserv_change_ticket_report_id;
        if (!fid) {
            return null;
        }
        return Array.isArray(fid) ? fid[0] : fid;
    },

    async fiservPrintChangeTicketRoutine() {
        try {
            if (!this._fiservHasChangeTicketReportConfigured()) {
                this.env.services.notification.add(
                    "No hay reporte de ticket de cambio configurado en el POS.",
                    {type: "warning"}
                );
                return;
            }
            const order = this.pos.get_order();
            if (!order) {
                this.env.services.notification.add("No se encontró la orden.", {type: "warning"});
                return;
            }

            const orderId = await this._fiservGetBackendOrderIdForChangeTicket();
            if (!orderId) {
                this.env.services.notification.add(
                    "La orden aún no está en el servidor. Intente en unos segundos.",
                    {type: "warning"}
                );
                return;
            }

            const reportId = this._fiservResolveChangeTicketReportId();
            let reportXmlId = null;
            try {
                const modelData = await this.orm.searchRead(
                    "ir.model.data",
                    [
                        ["model", "=", "ir.actions.report"],
                        ["res_id", "=", reportId],
                    ],
                    ["module", "name"],
                    {limit: 1}
                );
                if (modelData?.length) {
                    reportXmlId = `${modelData[0].module}.${modelData[0].name}`;
                }
            } catch (e) {
                console.error("odoo_pos_fiserv: ir.model.data reporte:", e);
            }
            if (!reportXmlId) {
                reportXmlId = "odoo_pos_fiserv_pos.action_report_pos_order_fiserv_change_ticket";
            }

            await this.report.doAction(reportXmlId, [orderId]);
            this.env.services.notification.add("Ticket de cambio (PDF) generado.", {type: "success"});
        } catch (error) {
            console.error("fiservPrintChangeTicketRoutine:", error);
            this.env.services.notification.add(
                `Error: ${error?.message || error?.toString() || String(error)}`,
                {type: "danger"}
            );
        }
    },

    async fiservPrintChangeTicketDocumentOnly() {
        return this.fiservPrintChangeTicketRoutine();
    },

    async fiservPrintVoucherOnly() {
        try {
            const order = this.pos.get_order();
            if (!order) {
                this.env.services.notification.add("No se encontró la orden.", {type: "warning"});
                return;
            }
            const orderId = await this._fiservGetBackendOrderIdForChangeTicket();
            const orderRef = order.pos_reference || order.name || false;
            if (!orderId && !orderRef) {
                this.env.services.notification.add("La orden aún no está en el servidor.", {
                    type: "warning",
                });
                return;
            }
            const txId = await this.orm.call(
                "pos.order",
                "get_fiserv_voucher_transaction_id_for_pos_print",
                [orderId || false, orderRef || false]
            );
            if (!txId) {
                this.env.services.notification.add(
                    "No hay transacción Fiserv / voucher para esta venta.",
                    {type: "info"}
                );
                return;
            }
            await this.report.doAction(
                "odoo_pos_fiserv_core.action_report_payment_transaction_fiserv_voucher",
                [txId]
            );
            this.env.services.notification.add("Voucher Fiserv ITD (PDF) generado.", {type: "success"});
        } catch (error) {
            console.error("fiservPrintVoucherOnly:", error);
            this.env.services.notification.add(
                `Error al imprimir voucher: ${error?.message || String(error)}`,
                {type: "danger"}
            );
        }
    },

    async fiservPrintLoyaltyCouponCode() {
        try {
            const orderId = await this._fiservGetBackendOrderIdForChangeTicket();
            if (!orderId) {
                this.env.services.notification.add("La orden aún no está en el servidor.", {
                    type: "warning",
                });
                return;
            }
            const posOrder = this.pos.get_order();
            let loyaltyCardIds = [];
            if (posOrder?.couponPointChanges && typeof posOrder.couponPointChanges === "object") {
                loyaltyCardIds = Object.keys(posOrder.couponPointChanges)
                    .map((k) => parseInt(k, 10))
                    .filter((n) => !Number.isNaN(n));
            }
            const data = await this.orm.call(
                "pos.order",
                "get_loyalty_coupon_code_print_data",
                [orderId],
                {loyalty_card_ids: loyaltyCardIds}
            );
            if (!data?.card_ids?.length || !data.report_xml_id) {
                this.env.services.notification.add(
                    "No hay cupón de promoción aplicado a esta venta.",
                    {type: "info"}
                );
                return;
            }
            await this.report.doAction(data.report_xml_id, data.card_ids);
            this.env.services.notification.add("Código de cupón enviado a impresión.", {type: "success"});
        } catch (error) {
            console.error("fiservPrintLoyaltyCouponCode:", error);
            const msg = error?.message || error?.data?.message || String(error);
            if (msg.includes("get_loyalty_coupon_code_print_data") || msg.includes("404")) {
                this.env.services.notification.add(
                    "No está disponible el método de cupón en el servidor (módulo de lealtad / impresión).",
                    {type: "warning"}
                );
            } else {
                this.env.services.notification.add(`Error: ${msg}`, {type: "danger"});
            }
        }
    },
});
