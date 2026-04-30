/** @odoo-module */

/**
 * Parchea ReceiptScreen para usar QZ Tray cuando está habilitado en pos.config.
 *
 * - Rutina: recibo + ticket de cambio + voucher OCA + cupón promoción (hasta 4 HTML, QZ).
 * - T-Cambio: solo ticket de cambio.
 * - Voucher: solo voucher OCA.
 * - Cupon PC: HTML del reporte «Código de cupón» (loyalty.card).
 */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

const _superPrintChangeTicketRoutine = ReceiptScreen.prototype.printChangeTicketRoutine;
const _superPrintChangeTicketDocumentOnly = ReceiptScreen.prototype.printChangeTicketDocumentOnly;
const _superPrintOcaVoucherOnly = ReceiptScreen.prototype.printOcaVoucherOnly;
const _superPrintLoyaltyCouponCode = ReceiptScreen.prototype.printLoyaltyCouponCode;
const _superPrintReceipt = ReceiptScreen.prototype.printReceipt;

const LOG = "[pos_forum_qz_print]";
const OCA_VOUCHER_LOG = "[odoo_pos_no_invoice][oca_voucher]";

/**
 * IDs de loyalty.card desde el pedido POS (claves de couponPointChanges; pos_loyalty).
 */
function collectLoyaltyCardIdsFromCurrentOrder(pos) {
    const order = pos.get_order();
    if (!order?.couponPointChanges || typeof order.couponPointChanges !== "object") {
        return [];
    }
    return Object.keys(order.couponPointChanges)
        .map((k) => parseInt(k, 10))
        .filter((n) => !Number.isNaN(n));
}

patch(ReceiptScreen.prototype, {
    /**
     * Comprueba si la ruta QZ está activa para documentos de ticket de cambio / voucher.
     */
    _qzTrayReadyForChangeFlow() {
        const cfg = this.pos.config;
        const qzPrint = this.env.services.qz_print;
        return !!(cfg.use_qz_tray && cfg.qz_tray_printer_name?.trim() && qzPrint);
    },

    /**
     * Resuelve orderId de servidor (misma lógica que odoo_pos_oca).
     */
    async _qzResolveOrderId() {
        return this._getBackendOrderIdForChangeTicket();
    },

    /**
     * HTML del recibo con voucher en datos (para Rutina).
     */
    async _qzBuildReceiptHtml() {
        const ord = this.pos.get_order();
        let ocaVoucherForReceipt = {};
        try {
            ocaVoucherForReceipt =
                (await this.orm.call("pos.order", "get_oca_voucher_dict_for_pos_receipt", [
                    ord.server_id || false,
                    ord.pos_reference || ord.name || false,
                ])) || {};
            if (!ocaVoucherForReceipt || typeof ocaVoucherForReceipt !== "object") {
                ocaVoucherForReceipt = {};
            }
        } catch (e) {
            console.warn(`${OCA_VOUCHER_LOG} _qzBuildReceiptHtml voucher dict`, e);
        }
        const receiptEl = await this.renderer.toHtml(OrderReceipt, {
            data: {
                ...ord.export_for_printing(),
                isBill: this.isBill,
                oca_voucher: ocaVoucherForReceipt,
            },
            formatCurrency: this.env.utils.formatCurrency,
        });
        return receiptEl.outerHTML;
    },

    /**
     * Descarga la rutina como un único PDF combinado cuando QZ no responde.
     *
     * Solo se invoca si ``cfg.qz_tray_download_on_failure`` está activo. En
     * lugar de hacer varias descargas seguidas (que el navegador bloquea como
     * pop-ups y además mezclan PDF y HTML), se envía un POST con el HTML del
     * recibo + el id del pedido al endpoint del servidor; el backend genera
     * los reportes que apliquen, los concatena con saltos de página y devuelve
     * un único PDF que el navegador descarga vía submit del form oculto.
     */
    async _downloadRoutineReports(orderId) {
        const order = this.pos.get_order();
        const loyaltyCardIds = collectLoyaltyCardIdsFromCurrentOrder(this.pos);

        let receiptHtml = "";
        try {
            receiptHtml = await this._qzBuildReceiptHtml();
        } catch (e) {
            console.warn(`${LOG} Fallback descarga: no se pudo construir el HTML del recibo | %s`, e);
        }

        // Bloque: form oculto con POST tradicional. Es la forma más fiable de
        // disparar la descarga de un binario: el browser lee el header
        // Content-Disposition y guarda el archivo sin abrir nueva pestaña.
        const form = document.createElement("form");
        form.method = "POST";
        form.action = "/pos_forum_qz_print/download_routine_pdf";
        form.target = "_self";
        form.style.display = "none";

        const addField = (name, value) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = name;
            input.value = value == null ? "" : String(value);
            form.appendChild(input);
        };

        // Bloque: token CSRF expuesto por Odoo en window.odoo.csrf_token.
        const csrfToken = (window.odoo && window.odoo.csrf_token) || "";
        addField("csrf_token", csrfToken);
        addField("order_id", orderId);
        addField("receipt_html", receiptHtml || "");
        addField("loyalty_card_ids", (loyaltyCardIds || []).join(","));

        document.body.appendChild(form);
        try {
            console.info(
                `${LOG} Fallback descarga: enviando form a /pos_forum_qz_print/download_routine_pdf | order_id=${orderId} | loyalty_cards=${
                    (loyaltyCardIds || []).join(",") || "(ninguna)"
                } | receipt_html_len=${(receiptHtml || "").length}`
            );
            form.submit();
        } finally {
            // Bloque: dejar el form un instante en el DOM para que el navegador
            // procese el submit antes de removerlo.
            setTimeout(() => {
                if (form.parentNode) {
                    form.parentNode.removeChild(form);
                }
            }, 1500);
        }

        const orderRef = order?.pos_reference || order?.name || "";
        this.env.services.notification.add(
            `QZ no disponible. Descargando PDF de rutina${orderRef ? ` (${orderRef})` : ""}.`,
            { type: "info" }
        );
    },

    /**
     * Rutina QZ: recibo + ticket de cambio + voucher OCA + cupón de promoción (si aplica).
     */
    async printChangeTicketRoutine() {
        const cfg = this.pos.config;
        const qzPrint = this.env.services.qz_print;
        if (!this._qzTrayReadyForChangeFlow()) {
            console.info(`${LOG} Rutina: sin QZ → PDF ticket de cambio (odoo_pos_oca).`);
            return _superPrintChangeTicketRoutine.call(this);
        }
        if (!cfg.change_ticket_report_id) {
            return _superPrintChangeTicketRoutine.call(this);
        }
        // Bloque: orderId se declara fuera del try para reutilizarlo en el
        // fallback de descarga del catch sin tener que volver a resolverlo.
        let orderId = null;
        try {
            const order = this.pos.get_order();
            if (!order) {
                this.env.services.notification.add("No se encontró la orden.", { type: "warning" });
                return;
            }
            orderId = await this._qzResolveOrderId();
            if (!orderId) {
                this.env.services.notification.add(
                    "La orden aún no está en el servidor. Intente de nuevo en unos segundos.",
                    { type: "warning" }
                );
                return;
            }
            const reportId = Array.isArray(cfg.change_ticket_report_id)
                ? cfg.change_ticket_report_id[0]
                : cfg.change_ticket_report_id;
            const html = await this.orm.call("pos.order", "get_change_ticket_html_for_pos_print", [
                orderId,
                reportId,
            ]);
            const receiptHtml = await this._qzBuildReceiptHtml();
            const voucherHtml = await this.orm.call(
                "pos.order",
                "get_oca_voucher_html_for_pos_print",
                [orderId],
                { raise_on_missing: false }
            );
            const loyaltyCardIds = collectLoyaltyCardIdsFromCurrentOrder(this.pos);
            let couponHtml = await this.orm.call(
                "pos.order",
                "get_loyalty_coupon_html_for_pos_print",
                [orderId],
                { loyalty_card_ids: loyaltyCardIds }
            );
            if (!couponHtml || !String(couponHtml).trim()) {
                couponHtml = "";
            }
            const parts = [receiptHtml, html];
            if (voucherHtml && String(voucherHtml).trim()) {
                parts.push(voucherHtml);
            }
            if (couponHtml && String(couponHtml).trim()) {
                parts.push(couponHtml);
            }
            await qzPrint.printSequentialHtmlDocuments(cfg.qz_tray_printer_name.trim(), parts);
            const desc = ["recibo", "ticket de cambio"];
            if (voucherHtml && String(voucherHtml).trim()) {
                desc.push("voucher OCA");
            }
            if (couponHtml && String(couponHtml).trim()) {
                desc.push("cupón de promoción");
            }
            this.env.services.notification.add(
                `Rutina QZ: ${desc.join(", ")} enviados a la impresora.`,
                { type: "success" }
            );
        } catch (error) {
            console.error(`${LOG} Rutina QZ error.`, error);
            // Bloque: fallback configurable según ``qz_tray_download_on_failure``.
            // Por default (False) solo se notifica el error sin descargar nada.
            // Si está activo, se descargan los 4 reportes (los que apliquen)
            // como PDF/HTML para que el operador los imprima manualmente.
            if (cfg.qz_tray_download_on_failure && orderId) {
                this.env.services.notification.add(
                    `QZ no disponible: ${error?.message || String(error)}. Descargando reportes...`,
                    { type: "warning" }
                );
                return await this._downloadRoutineReports(orderId);
            }
            this.env.services.notification.add(
                `No se pudo conectar a la impresora QZ: ${error?.message || String(error)}. ` +
                "Active 'Descargar reportes si QZ falla' en la configuración del POS si quiere obtener los documentos.",
                { type: "warning" }
            );
        }
    },

    /**
     * Solo ticket de cambio (QZ: HTML; sin QZ: PDF único).
     */
    async printChangeTicketDocumentOnly() {
        if (!this._qzTrayReadyForChangeFlow()) {
            return _superPrintChangeTicketDocumentOnly.call(this);
        }
        const cfg = this.pos.config;
        if (!cfg.change_ticket_report_id) {
            return _superPrintChangeTicketDocumentOnly.call(this);
        }
        try {
            const orderId = await this._qzResolveOrderId();
            if (!orderId) {
                this.env.services.notification.add(
                    "La orden aún no está en el servidor.",
                    { type: "warning" }
                );
                return;
            }
            const reportId = Array.isArray(cfg.change_ticket_report_id)
                ? cfg.change_ticket_report_id[0]
                : cfg.change_ticket_report_id;
            const html = await this.orm.call("pos.order", "get_change_ticket_html_for_pos_print", [
                orderId,
                reportId,
            ]);
            await this.env.services.qz_print.printHtml(cfg.qz_tray_printer_name.trim(), html);
            this.env.services.notification.add("Ticket de cambio enviado a la impresora (QZ).", {
                type: "success",
            });
        } catch (error) {
            console.error(`${LOG} T-Cambio QZ error`, error);
            return _superPrintChangeTicketDocumentOnly.call(this);
        }
    },

    /**
     * Solo voucher OCA.
     */
    async printOcaVoucherOnly() {
        if (!this._qzTrayReadyForChangeFlow()) {
            return _superPrintOcaVoucherOnly.call(this);
        }
        try {
            const orderId = await this._qzResolveOrderId();
            if (!orderId) {
                this.env.services.notification.add(
                    "La orden aún no está en el servidor.",
                    { type: "warning" }
                );
                return;
            }
            const voucherHtml = await this.orm.call(
                "pos.order",
                "get_oca_voucher_html_for_pos_print",
                [orderId],
                { raise_on_missing: false }
            );
            if (!voucherHtml || !String(voucherHtml).trim()) {
                this.env.services.notification.add(
                    "No hay voucher OCA para esta venta.",
                    { type: "info" }
                );
                return;
            }
            await this.env.services.qz_print.printHtml(
                this.pos.config.qz_tray_printer_name.trim(),
                voucherHtml
            );
            this.env.services.notification.add("Voucher OCA enviado a la impresora (QZ).", {
                type: "success",
            });
        } catch (error) {
            console.error(`${LOG} Voucher solo QZ error`, error);
            return _superPrintOcaVoucherOnly.call(this);
        }
    },

    /**
     * Cupón promoción: HTML del reporte loyalty (Código de cupón).
     */
    async printLoyaltyCouponCode() {
        if (!this._qzTrayReadyForChangeFlow()) {
            return _superPrintLoyaltyCouponCode.call(this);
        }
        try {
            const orderId = await this._qzResolveOrderId();
            if (!orderId) {
                this.env.services.notification.add(
                    "La orden aún no está en el servidor.",
                    { type: "warning" }
                );
                return;
            }
            const loyaltyCardIds = collectLoyaltyCardIdsFromCurrentOrder(this.pos);
            const html = await this.orm.call(
                "pos.order",
                "get_loyalty_coupon_html_for_pos_print",
                [orderId],
                { loyalty_card_ids: loyaltyCardIds }
            );
            if (!html || !String(html).trim()) {
                this.env.services.notification.add(
                    "No hay cupón de promoción para esta venta.",
                    { type: "info" }
                );
                return;
            }
            await this.env.services.qz_print.printHtml(
                this.pos.config.qz_tray_printer_name.trim(),
                html
            );
            this.env.services.notification.add("Código de cupón enviado a la impresora (QZ).", {
                type: "success",
            });
        } catch (error) {
            console.error(`${LOG} Cupon PC QZ error → PDF`, error);
            return _superPrintLoyaltyCouponCode.call(this);
        }
    },

    /**
     * Recibo POS con QZ (sin cambios de lógica respecto al parche anterior).
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
            return _superPrintReceipt.call(this);
        }
        const btn = this.buttonPrintReceipt.el;
        if (btn) {
            btn.className = "fa fa-fw fa-spin fa-circle-o-notch";
        }
        try {
            const order = this.pos.get_order();
            const base = order.export_for_printing();
            const orderRef = order.pos_reference || order.name || "";
            let ocaVoucher = {};
            try {
                ocaVoucher =
                    (await this.env.services.orm.call("pos.order", "get_oca_voucher_dict_for_pos_receipt", [
                        order.server_id || false,
                        orderRef || false,
                    ])) || {};
                if (!ocaVoucher || typeof ocaVoucher !== "object") {
                    ocaVoucher = {};
                }
            } catch (e) {
                console.warn(`${OCA_VOUCHER_LOG} printReceipt(QZ) voucher RPC error`, e);
            }
            const el = await this.renderer.toHtml(OrderReceipt, {
                data: {
                    ...base,
                    isBill: this.isBill,
                    oca_voucher: ocaVoucher,
                },
                formatCurrency: this.env.utils.formatCurrency,
            });
            await qzPrint.printHtml(cfg.qz_tray_printer_name.trim(), el.outerHTML);
            this.currentOrder._printed = true;
        } catch (error) {
            console.error(`${LOG} Recibo POS: error QZ; impresión estándar.`, error);
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
