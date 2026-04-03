/** @odoo-module */
/**
 * Override del ReceiptScreen para controlar la impresión web según la configuración.
 *
 * Este módulo evita que se abra el diálogo de impresión del navegador cuando
 * el POS tiene desmarcada la opción "download_invoice", respetando el requerimiento
 * de no descargar/mostrar PDF en esos casos.
 */

import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";

/** Mismo prefijo que en receipt_cfe_data.js para filtrar trazas del voucher en impresión. */
const OCA_VOUCHER_LOG = "[odoo_pos_no_invoice][oca_voucher]";

patch(ReceiptScreen.prototype, {
    /**
     * Imprime el recibo respetando la configuración de descarga.
     *
     * Si download_invoice está desmarcado, se desactiva el fallback de impresión web
     * para evitar la descarga/impresión PDF desde el navegador.
     */
    async printReceipt() {
        // Mostrar estado de carga en el botón de impresión.
        if (this.buttonPrintReceipt?.el) {
            this.buttonPrintReceipt.el.className = "fa fa-fw fa-spin fa-circle-o-notch";
        }

        // Determinar si se permite el fallback a impresión web.
        const allowWebPrintFallback = !!this.pos.config.download_invoice;

        // Preparar los datos del recibo con el estado actual del pedido.
        const order = this.pos.get_order();
        const orderReference = order?.pos_reference || order?.name || "";
        const orderServerId = order?.server_id || null;
        let accountMoveId = null;
        if (order?.account_move) {
            if (Array.isArray(order.account_move)) {
                accountMoveId = order.account_move[0];
            } else if (typeof order.account_move === "object" && order.account_move.id) {
                accountMoveId = order.account_move.id;
            } else if (typeof order.account_move === "number") {
                accountMoveId = order.account_move;
            }
        }

        // Intentar obtener datos del recibo desde la factura antes de imprimir.
        let receiptServerData = null;
        const orm = this.env.services.orm;
        const maxAttempts = 20;
        for (let attempt = 0; attempt < maxAttempts; attempt++) {
            try {
                receiptServerData = await orm.call(
                    "pos.order",
                    "get_receipt_data_from_invoice_or_order",
                    [[], accountMoveId, orderReference, orderServerId]
                );
                if (
                    receiptServerData?.source === "invoice" &&
                    receiptServerData?.orderlines?.length
                ) {
                    break;
                }
            } catch (error) {
                console.error("Error al obtener datos de la factura para el recibo:", error);
                break;
            }
            await new Promise((resolve) => setTimeout(resolve, 1000));
        }

        const baseReceiptData = this.pos.get_order().export_for_printing();

        // Bloque: voucher OCA (id backend y/o referencia si aún no hay server_id).
        let ocaVoucher = {};
        try {
            ocaVoucher =
                (await orm.call("pos.order", "get_oca_voucher_dict_for_pos_receipt", [
                    orderServerId || false,
                    orderReference || false,
                ])) || {};
            if (!ocaVoucher || typeof ocaVoucher !== "object") {
                ocaVoucher = {};
            }
        } catch (e) {
            console.warn(`${OCA_VOUCHER_LOG} printReceipt RPC error`, e);
        }

        console.info(
            `${OCA_VOUCHER_LOG} printReceipt antes de printer.print | orderServerId=${orderServerId} ` +
                `orderReference=${JSON.stringify(orderReference)} | oca_keys=${Object.keys(
                    ocaVoucher
                ).join(",")} | show_client_copy=${ocaVoucher.show_client_copy} | payload=${JSON.stringify(
                    ocaVoucher
                )}`
        );

        // Obtener datos del CFE para incluirlos en el recibo impreso.
        let cfeData = {};
        const accountMoveIdForCfe = accountMoveId || receiptServerData?.account_move_id || null;
        if (accountMoveIdForCfe) {
            try {
                const rawCfeData = await orm.call(
                    "pos.order",
                    "get_cfe_data_from_invoice",
                    [[], accountMoveIdForCfe]
                ) || {};
                if (rawCfeData && (rawCfeData.tipo || rawCfeData.serie || rawCfeData.numero)) {
                    cfeData = { ...rawCfeData };
                    cfeData.vta_cont = order?.pos_reference || order?.name || "";
                    cfeData.caja = order?.session_id ? (order.session_id.name || "") : "";
                    cfeData.cajero = order?.user_id ? (order.user_id.name || "") : "";
                    cfeData.vend = "0";
                    cfeData.store = order?.config_id ? `STORE-${order.config_id.id}` : "";
                    if (order?.payment_ids?.length > 0) {
                        const pm = order.payment_ids[0].payment_method_id;
                        cfeData.pago = pm ? (pm.name || "Contado") : "Contado";
                    } else {
                        cfeData.pago = "Contado";
                    }
                    console.log("✓ Datos CFE cargados para impresión:", cfeData);
                }
            } catch (e) {
                console.error("Error al obtener datos CFE para impresión:", e);
            }
        }

        const receiptData = {
            ...baseReceiptData,
            ...(receiptServerData || {}),
            isBill: this.isBill,
            oca_voucher: ocaVoucher,
            cfe_data: cfeData,
        };
        if (!receiptServerData?.orderlines?.length) {
            receiptData.orderlines = baseReceiptData.orderlines;
        }
        if (!receiptServerData?.paymentlines?.length) {
            receiptData.paymentlines = baseReceiptData.paymentlines;
        }

        // Ejecutar impresión con el fallback condicionado a la configuración.
        const isPrinted = await this.printer.print(
            OrderReceipt,
            {
                data: receiptData,
                formatCurrency: this.env.utils.formatCurrency,
            },
            { webPrintFallback: allowWebPrintFallback }
        );

        // Marcar el pedido como impreso si la operación fue exitosa.
        if (isPrinted) {
            this.currentOrder._printed = true;
        }

        // Restaurar el icono del botón de impresión.
        if (this.buttonPrintReceipt?.el) {
            this.buttonPrintReceipt.el.className = "fa fa-print";
        }
    },
});
