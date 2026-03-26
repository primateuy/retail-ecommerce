/** @odoo-module */

/**
 * Parchea ReceiptScreen para usar QZ Tray cuando está habilitado en pos.config.
 *
 * - Ticket de cambio: HTML QWeb vía RPC + QZ (si falla QZ, delega en odoo_pos_oca).
 * - Recibo POS: opcional con qz_tray_print_pos_receipt (HTML del OrderReceipt + QZ).
 */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

const _superPrintChangeTicket = ReceiptScreen.prototype.printChangeTicket;
const _superPrintReceipt = ReceiptScreen.prototype.printReceipt;

/** Prefijo para consola del navegador (F12 → filtrar pos_forum_qz_print). */
const LOG = "[pos_forum_qz_print]";

patch(ReceiptScreen.prototype, {
    /**
     * Ticket de cambio: ruta QZ si use_qz_tray y nombre de impresora; si no, super.
     */
    async printChangeTicket() {
        const cfg = this.pos.config;
        const qzPrint = this.env.services.qz_print;
        if (!cfg.use_qz_tray || !cfg.qz_tray_printer_name?.trim() || !qzPrint) {
            console.info(
                `${LOG} Ticket cambio: sin ruta QZ → método estándar (odoo_pos_oca). ` +
                    `use_qz_tray=${Boolean(cfg.use_qz_tray)} ` +
                    `impresora_configurada=${Boolean(cfg.qz_tray_printer_name?.trim())} ` +
                    `servicio_qz=${Boolean(qzPrint)}`
            );
            return _superPrintChangeTicket.call(this);
        }
        console.info(
            `${LOG} Ticket cambio: ruta QZ activa | impresora=${JSON.stringify(
                cfg.qz_tray_printer_name.trim()
            )}`
        );
        try {
            if (!this.pos.config.change_ticket_report_id) {
                console.warn(
                    `${LOG} Ticket cambio: no hay reporte configurado; se delega al estándar.`
                );
                return _superPrintChangeTicket.call(this);
            }
            const order = this.pos.get_order();
            if (!order) {
                console.warn(`${LOG} Ticket cambio: no hay orden actual en el POS.`);
                this.env.services.notification.add(
                    "No se encontró la orden para imprimir el ticket de cambio.",
                    { type: "warning" }
                );
                return;
            }
            let orderId = order.server_id || order.id;
            if (!orderId) {
                try {
                    const orderData = order.export_for_printing();
                    if (orderData && orderData.id) {
                        orderId = orderData.id;
                        console.info(
                            `${LOG} Ticket cambio: orderId obtenido de export_for_printing → ${orderId}`
                        );
                    }
                } catch (e) {
                    console.warn(`${LOG} Ticket cambio: export_for_printing falló:`, e);
                }
            }
            if (!orderId && (order.name || order.pos_reference)) {
                const orderRef = order.name || order.pos_reference;
                console.info(
                    `${LOG} Ticket cambio: buscando orden en servidor por referencia=${JSON.stringify(
                        orderRef
                    )}`
                );
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
                if (searchResult && searchResult.length > 0) {
                    orderId = searchResult[0].id;
                    console.info(
                        `${LOG} Ticket cambio: orden encontrada en servidor | order_id=${orderId}`
                    );
                }
            }
            if (!orderId) {
                console.warn(
                    `${LOG} Ticket cambio: sin order_id de servidor; no se envía nada a QZ ni RPC.`
                );
                this.env.services.notification.add(
                    "La orden aún no está en el servidor. Intente de nuevo en unos segundos.",
                    { type: "warning" }
                );
                return;
            }
            const reportId = Array.isArray(this.pos.config.change_ticket_report_id)
                ? this.pos.config.change_ticket_report_id[0]
                : this.pos.config.change_ticket_report_id;
            console.info(
                `${LOG} Ticket cambio: solicitando HTML al servidor | order_id=${orderId} report_id=${reportId}`
            );
            const html = await this.orm.call(
                "pos.order",
                "get_change_ticket_html_for_pos_print",
                [orderId, reportId]
            );

            // Bloque: desde el botón "Ticket de cambio" imprimir 2 reportes:
            // 1) recibo de pago (OrderReceipt)
            // 2) corte ESC/POS
            // 3) ticket de cambio (QWeb)
            console.info(`${LOG} Ticket cambio: preparando recibo de pago para impresión doble con corte.`);
            const receiptEl = await this.renderer.toHtml(OrderReceipt, {
                data: {
                    ...this.pos.get_order().export_for_printing(),
                    isBill: this.isBill,
                },
                formatCurrency: this.env.utils.formatCurrency,
            });
            const receiptHtml = receiptEl.outerHTML;
            console.info(
                `${LOG} Ticket cambio: HTMLs listos | recibo_len=${receiptHtml.length} | cambio_len=${
                    html ? String(html).length : 0
                }`
            );

            await qzPrint.printTwoHtmlWithEscPosCutBetween(
                cfg.qz_tray_printer_name.trim(),
                receiptHtml,
                html
            );
            console.info(`${LOG} Ticket cambio: impresión doble con corte completada.`);
            this.env.services.notification.add(
                "Recibo y ticket de cambio enviados a la impresora (QZ Tray).",
                { type: "success" }
            );
        } catch (error) {
            console.error(
                `${LOG} Ticket cambio: error en ruta QZ; se delega al método estándar.`,
                error
            );
            const msg = error?.message || String(error);
            this.env.services.notification.add(
                `QZ Tray: ${msg}. Se usará el método estándar.`,
                { type: "warning" }
            );
            return _superPrintChangeTicket.call(this);
        }
    },

    /**
     * Recibo POS: QZ solo si los tres flags/nombre están definidos; si no, super.
     */
    async printReceipt() {
        const cfg = this.pos.config;
        const qzPrint = this.env.services.qz_print;
        if (
            !cfg.use_qz_tray ||
            !cfg.qz_tray_printer_name?.trim() ||
            !cfg.qz_tray_print_pos_receipt ||
            !qzPrint
        ) {
            console.info(
                `${LOG} Recibo POS: sin ruta QZ → impresión estándar. ` +
                    `use_qz=${Boolean(cfg.use_qz_tray)} ` +
                    `nombre_impresora=${Boolean(cfg.qz_tray_printer_name?.trim())} ` +
                    `opcion_recibo_qz=${Boolean(cfg.qz_tray_print_pos_receipt)} ` +
                    `servicio=${Boolean(qzPrint)}`
            );
            return _superPrintReceipt.call(this);
        }
        console.info(
            `${LOG} Recibo POS: ruta QZ | impresora=${JSON.stringify(
                cfg.qz_tray_printer_name.trim()
            )}`
        );
        const btn = this.buttonPrintReceipt.el;
        if (btn) {
            btn.className = "fa fa-fw fa-spin fa-circle-o-notch";
        }
        try {
            const el = await this.renderer.toHtml(OrderReceipt, {
                data: {
                    ...this.pos.get_order().export_for_printing(),
                    isBill: this.isBill,
                },
                formatCurrency: this.env.utils.formatCurrency,
            });
            await qzPrint.printHtml(cfg.qz_tray_printer_name.trim(), el.outerHTML);
            this.currentOrder._printed = true;
            console.info(`${LOG} Recibo POS: QZ completado; orden marcada como impresa.`);
        } catch (error) {
            console.error(
                `${LOG} Recibo POS: error QZ; se intenta impresión estándar.`,
                error
            );
            this.env.services.notification.add(error?.message || String(error), {
                type: "danger",
            });
            await _superPrintReceipt.call(this);
        } finally {
            if (this.buttonPrintReceipt.el) {
                this.buttonPrintReceipt.el.className = "fa fa-print";
            }
        }
    },
});
