/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * Extensión de ReceiptScreen: ticket de cambio y fila de acciones (Rutina, T-Cambio,
 * Voucher, Cupon PC). La impresión QZ detallada la aporta pos_forum_qz_print.
 */
patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.report = useService("report");

        onMounted(() => {
            setTimeout(() => {
                this._addChangeTicketButtonSafely();
            }, 500);
        });

        onWillUnmount(() => {
            this._removeChangeTicketButton();
        });
    },

    /**
     * Inserta una fila con 4 botones compactos debajo de «Imprimir recibo».
     */
    _addChangeTicketButtonSafely() {
        if (!this.pos.config.change_ticket_report_id) {
            return;
        }

        if (document.querySelector(".change-ticket-actions-row")) {
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
        newButtonContainer.className = "change-ticket-container mt-2 w-100";
        newButtonContainer.style.marginTop = "0.5rem";

        const row = document.createElement("div");
        row.className = "change-ticket-actions-row d-flex flex-wrap justify-content-stretch w-100";
        row.style.gap = "0.5rem";

        /**
         * Botón compacto con icono FontAwesome y etiqueta en negrita (mejor lectura en caja).
         */
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
            mkBtn(
                "Rutina",
                "Recibo + ticket de cambio + voucher empresa (flujo completo)",
                "fa-tasks",
                () => this.printChangeTicketRoutine()
            )
        );
        row.appendChild(
            mkBtn("T-Cambio", "Solo ticket de cambio", "fa-exchange", () =>
                this.printChangeTicketDocumentOnly()
            )
        );
        row.appendChild(
            mkBtn("Voucher", "Solo voucher tarjeta OCA", "fa-credit-card", () =>
                this.printOcaVoucherOnly()
            )
        );
        row.appendChild(
            mkBtn("Cupón PC", "Código de cupón de promoción (lealtad)", "fa-tag", () =>
                this.printLoyaltyCouponCode()
            )
        );

        newButtonContainer.appendChild(row);

        if (printButtonContainer) {
            if (printButtonContainer.nextSibling) {
                printButtonContainer.parentNode.insertBefore(newButtonContainer, printButtonContainer.nextSibling);
            } else {
                printButtonContainer.parentNode.appendChild(newButtonContainer);
            }
        } else {
            actionsArea.appendChild(newButtonContainer);
        }
    },

    _removeChangeTicketButton() {
        const container = document.querySelector(".change-ticket-container");
        if (container) {
            container.remove();
        }
    },

    /**
     * Resuelve el ID backend de la orden POS para RPC e informes.
     */
    async _getBackendOrderIdForChangeTicket() {
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
                console.warn("odoo_pos_oca: export_for_printing sin id:", e);
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
                    { limit: 1 }
                );
                if (searchResult?.length) {
                    orderId = searchResult[0].id;
                }
            } catch (e) {
                console.warn("odoo_pos_oca: búsqueda orden por referencia:", e);
            }
        }
        return orderId || null;
    },

    /**
     * Rutina (sin QZ): PDF del ticket de cambio. Con QZ lo redefine pos_forum_qz_print.
     */
    async printChangeTicketRoutine() {
        try {
            if (!this.pos.config.change_ticket_report_id) {
                this.env.services.notification.add(
                    "No hay reporte de ticket de cambio configurado en el POS.",
                    { type: "warning" }
                );
                return;
            }
            const order = this.pos.get_order();
            if (!order) {
                this.env.services.notification.add("No se encontró la orden.", { type: "warning" });
                return;
            }

            const orderId = await this._getBackendOrderIdForChangeTicket();
            if (!orderId) {
                this.env.services.notification.add(
                    "La orden aún no está en el servidor. Intente en unos segundos.",
                    { type: "warning" }
                );
                return;
            }

            const reportId = Array.isArray(this.pos.config.change_ticket_report_id)
                ? this.pos.config.change_ticket_report_id[0]
                : this.pos.config.change_ticket_report_id;

            let reportXmlId = null;
            try {
                const modelData = await this.orm.searchRead(
                    "ir.model.data",
                    [
                        ["model", "=", "ir.actions.report"],
                        ["res_id", "=", reportId],
                    ],
                    ["module", "name"],
                    { limit: 1 }
                );
                if (modelData?.length) {
                    reportXmlId = `${modelData[0].module}.${modelData[0].name}`;
                } else {
                    reportXmlId = "odoo_pos_oca.action_report_pos_order_change_ticket";
                }
            } catch (e) {
                console.error("Error al obtener XML ID del reporte:", e);
                reportXmlId = "odoo_pos_oca.action_report_pos_order_change_ticket";
            }

            if (!reportXmlId) {
                this.env.services.notification.add("No se pudo resolver el reporte del ticket de cambio.", {
                    type: "warning",
                });
                return;
            }

            await this.report.doAction(reportXmlId, [orderId]);
            this.env.services.notification.add("Ticket de cambio (PDF) generado.", { type: "success" });
        } catch (error) {
            console.error("printChangeTicketRoutine:", error);
            this.env.services.notification.add(
                `Error: ${error?.message || error?.toString() || String(error)}`,
                { type: "danger" }
            );
        }
    },

    /**
     * Compatibilidad: botones encadenados y código antiguo llaman a `printChangeTicket`.
     */
    async printChangeTicket() {
        return this.printChangeTicketRoutine();
    },

    /**
     * Solo documento de ticket de cambio (PDF en flujo sin QZ).
     */
    async printChangeTicketDocumentOnly() {
        return this.printChangeTicketRoutine();
    },

    /**
     * Solo voucher OCA (PDF del reporte de payment.transaction).
     */
    async printOcaVoucherOnly() {
        try {
            const order = this.pos.get_order();
            if (!order) {
                this.env.services.notification.add("No se encontró la orden.", { type: "warning" });
                return;
            }
            const orderId = await this._getBackendOrderIdForChangeTicket();
            const orderRef = order.pos_reference || order.name || false;
            if (!orderId && !orderRef) {
                this.env.services.notification.add("La orden aún no está en el servidor.", {
                    type: "warning",
                });
                return;
            }
            const txId = await this.orm.call('pos.order', 'get_oca_voucher_transaction_id_for_pos_print', [
                orderId || false,
                orderRef || false,
            ]);
            if (!txId) {
                this.env.services.notification.add(
                    "No hay transacción OCA / voucher para esta venta.",
                    { type: "info" }
                );
                return;
            }
            await this.report.doAction("odoo_pos_oca.action_report_payment_transaction_oca_voucher", [txId]);
            this.env.services.notification.add("Voucher OCA (PDF) generado.", { type: "success" });
        } catch (error) {
            console.error("printOcaVoucherOnly:", error);
            this.env.services.notification.add(
                `Error al imprimir voucher: ${error?.message || String(error)}`,
                { type: "danger" }
            );
        }
    },

    /**
     * Reporte «Código de cupón» (loyalty.card) si existe promoción en la orden.
     */
    async printLoyaltyCouponCode() {
        try {
            const orderId = await this._getBackendOrderIdForChangeTicket();
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
                { loyalty_card_ids: loyaltyCardIds }
            );
            if (!data?.card_ids?.length || !data.report_xml_id) {
                this.env.services.notification.add(
                    "No hay cupón de promoción aplicado a esta venta.",
                    { type: "info" }
                );
                return;
            }
            await this.report.doAction(data.report_xml_id, data.card_ids);
            this.env.services.notification.add("Código de cupón enviado a impresión.", { type: "success" });
        } catch (error) {
            console.error("printLoyaltyCouponCode:", error);
            const msg = error?.message || error?.data?.message || String(error);
            if (msg.includes("get_loyalty_coupon_code_print_data") || msg.includes("404")) {
                this.env.services.notification.add(
                    "No está disponible el módulo de cupón (pos_forum_qz_print + pos_loyalty).",
                    { type: "warning" }
                );
            } else {
                this.env.services.notification.add(`Error: ${msg}`, { type: "danger" });
            }
        }
    },
});
