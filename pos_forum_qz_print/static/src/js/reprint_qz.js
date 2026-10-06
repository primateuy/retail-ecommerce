/** @odoo-module */

/**
 * Reimpresión desde la lista de órdenes por QZ Tray.
 *
 * Sin esto la reimpresión nunca pasaba por QZ: el botón Imprimir de la lista
 * llama a printer.print(), que sin impresora IoT/ePos devuelve false y abre
 * ReprintReceiptScreen; y el «Imprimir recibo» de esa pantalla termina en un
 * window.print() del navegador, que no llega a la térmica.
 *
 * Con QZ activo en la caja se imprime lo mismo que «Imprimir Boleta» más el
 * voucher OCA (COPIA EMPRESA), en el orden de la Rutina: recibo → voucher.
 * La COPIA CLIENTE ya va dentro del recibo. Si QZ falla, se avisa y sigue el
 * camino de antes.
 */

import { patch } from "@web/core/utils/patch";
import { ReprintReceiptButton } from "@point_of_sale/app/screens/ticket_screen/reprint_receipt_button/reprint_receipt_button";
import { ReprintReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/reprint_receipt_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { buildReceiptPrintData, getOrderServerId } from "@pos_forum_qz_print/js/receipt_data_qz";

const LOG = "[pos_forum_qz_print]";

/**
 * La caja imprime el recibo por QZ (mismas condiciones que «Imprimir Boleta»).
 */
function qzReceiptEnabled(env, pos) {
    const cfg = pos.config;
    return !!(
        cfg.use_qz_tray &&
        cfg.qz_tray_printer_name?.trim() &&
        cfg.qz_tray_print_pos_receipt &&
        env.services.qz_print
    );
}

/**
 * Imprime recibo + voucher OCA de `order` por QZ. Lanza si algo falla.
 */
async function reprintOrderWithQz(env, pos, order) {
    const receiptData = await buildReceiptPrintData(env, order);
    const el = await env.services.renderer.toHtml(OrderReceipt, {
        data: receiptData,
        formatCurrency: env.utils.formatCurrency,
    });
    if (!el) {
        throw new Error("No se pudo armar el recibo para imprimir.");
    }
    const parts = [el.outerHTML];
    const labels = ["recibo"];

    const orderServerId = getOrderServerId(order);
    if (orderServerId) {
        try {
            const voucherHtml = await env.services.orm.call(
                "pos.order",
                "get_oca_voucher_html_for_pos_print",
                [orderServerId],
                { raise_on_missing: false }
            );
            if (voucherHtml && String(voucherHtml).trim()) {
                parts.push(voucherHtml);
                labels.push("voucher OCA");
            }
        } catch (e) {
            // Bloque: sin voucher igual se imprime el recibo.
            console.warn(`${LOG} Reimpresión: no se pudo obtener el voucher OCA`, e);
        }
    }

    await env.services.qz_print.printSequentialHtmlDocuments(
        pos.config.qz_tray_printer_name.trim(),
        parts,
        { labels }
    );
}

function notifyQzError(env, error) {
    console.error(`${LOG} Reimpresión: error QZ; impresión estándar.`, error);
    env.services.notification.add(
        `QZ no imprimió el recibo: ${error?.message || String(error)}`,
        { type: "danger" }
    );
}

patch(ReprintReceiptButton.prototype, {
    async click() {
        if (!this.props.order || !qzReceiptEnabled(this.env, this.pos)) {
            return super.click(...arguments);
        }
        try {
            await reprintOrderWithQz(this.env, this.pos, this.props.order);
        } catch (error) {
            notifyQzError(this.env, error);
            return super.click(...arguments);
        }
    },
});

patch(ReprintReceiptScreen.prototype, {
    async tryReprint() {
        if (!qzReceiptEnabled(this.env, this.pos)) {
            return super.tryReprint(...arguments);
        }
        try {
            await reprintOrderWithQz(this.env, this.pos, this.props.order);
        } catch (error) {
            notifyQzError(this.env, error);
            return super.tryReprint(...arguments);
        }
    },
});