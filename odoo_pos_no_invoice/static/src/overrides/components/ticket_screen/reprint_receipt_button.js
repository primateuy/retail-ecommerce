/** @odoo-module */
/**
 * Override de ReprintReceiptButton para incluir datos del CFE al reimprimir
 * desde la pantalla de tickets (órdenes sincronizadas).
 */

import { ReprintReceiptButton } from "@point_of_sale/app/screens/ticket_screen/reprint_receipt_button/reprint_receipt_button";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(ReprintReceiptButton.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
    },

    async click() {
        if (!this.props.order) {
            return;
        }

        const order = this.props.order;
        const orderReference = order.pos_reference || order.name || "";
        const orderServerId = order.server_id || order.id || null;

        // Obtener account_move_id desde la orden.
        let accountMoveId = null;
        if (order.account_move) {
            if (Array.isArray(order.account_move)) {
                accountMoveId = order.account_move[0];
            } else if (typeof order.account_move === "object" && order.account_move.id) {
                accountMoveId = order.account_move.id;
            } else if (typeof order.account_move === "number") {
                accountMoveId = order.account_move;
            }
        }

        const baseReceiptData = order.export_for_printing();

        // Obtener datos del recibo desde la factura si está disponible.
        let receiptServerData = null;
        try {
            receiptServerData = await this.orm.call(
                "pos.order",
                "get_receipt_data_from_invoice_or_order",
                [[], accountMoveId, orderReference, orderServerId]
            );
        } catch (e) {
            console.error("Error al obtener datos del recibo para reimpresión:", e);
        }

        // Obtener datos del CFE.
        let cfeData = {};
        const accountMoveIdForCfe = accountMoveId || receiptServerData?.account_move_id || null;
        if (accountMoveIdForCfe) {
            try {
                const rawCfeData = await this.orm.call(
                    "pos.order",
                    "get_cfe_data_from_invoice",
                    [[], accountMoveIdForCfe]
                ) || {};
                if (rawCfeData && (rawCfeData.tipo || rawCfeData.serie || rawCfeData.numero)) {
                    cfeData = { ...rawCfeData };
                    cfeData.vta_cont = order.pos_reference || order.name || "";
                    cfeData.caja = order.session_id ? (order.session_id.name || "") : "";
                    cfeData.cajero = order.user_id ? (order.user_id.name || "") : "";
                    cfeData.vend = "0";
                    cfeData.store = order.config_id ? `STORE-${order.config_id.id}` : "";
                    if (order.payment_ids?.length > 0) {
                        const pm = order.payment_ids[0].payment_method_id;
                        cfeData.pago = pm ? (pm.name || "Contado") : "Contado";
                    } else {
                        cfeData.pago = "Contado";
                    }
                    console.log("✓ Datos CFE cargados para reimpresión:", cfeData);
                }
            } catch (e) {
                console.error("Error al obtener datos CFE para reimpresión:", e);
            }
        }

        const receiptData = {
            ...baseReceiptData,
            ...(receiptServerData?.source === "invoice" && receiptServerData?.orderlines?.length
                ? receiptServerData
                : {}),
            cfe_data: cfeData,
        };
        if (!receiptServerData?.orderlines?.length) {
            receiptData.orderlines = baseReceiptData.orderlines;
        }
        if (!receiptServerData?.paymentlines?.length) {
            receiptData.paymentlines = baseReceiptData.paymentlines;
        }

        // El barcode del servidor se arrastra siempre, incluso cuando los datos
        // vienen de la orden y no de la factura: si no, la reimpresión cae al
        // fallback por URL (/report/barcode/), que devuelve el PNG estirado y
        // borroso que justamente no se puede escanear.
        if (receiptServerData?.barcode) {
            receiptData.barcode = receiptServerData.barcode;
            this.pos._reprintBarcode = receiptServerData.barcode;
        }

        // Guardar CFE data en el store para que _loadReceiptData lo use
        // cuando ReprintReceiptScreen renderice OrderReceipt sin cfe_data en props.
        this.pos._reprintCfeData = cfeData;

        (await this.printer.print(OrderReceipt, {
            data: receiptData,
            formatCurrency: this.env.utils.formatCurrency,
        })) || this.pos.showScreen("ReprintReceiptScreen", { order });
    },
});
