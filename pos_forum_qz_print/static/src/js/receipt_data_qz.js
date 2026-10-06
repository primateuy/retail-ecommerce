/** @odoo-module */

/**
 * Datos del recibo para imprimir por QZ, comunes a todas las vías.
 *
 * Lo usan el botón «Imprimir Boleta» y la Rutina (receipt_screen_qz.js) y la
 * reimpresión desde la lista de órdenes (reprint_qz.js). Antes la misma carga
 * estaba copiada en cada una; si una vía arma los datos distinto, el ticket sale
 * distinto según el botón que se toque.
 *
 * Siempre devuelve `_skipAsyncReload: true`: los datos ya vienen cargados, y si
 * receipt_cfe_data.js relanza las RPC en onMounted mientras el RenderContainer
 * aislado de renderer.toHtml() captura el render, el Fiber de Owl no completa
 * nunca y toHtml() resuelve null.
 */

const LOG = "[pos_forum_qz_print]";
const OCA_VOUCHER_LOG = "[odoo_pos_no_invoice][oca_voucher]";

/**
 * ID de la factura de la orden, venga como lista, objeto o número.
 */
export function getAccountMoveId(order) {
    const move = order?.account_move;
    if (!move) {
        return null;
    }
    if (Array.isArray(move)) {
        return move[0];
    }
    if (typeof move === "object" && move.id) {
        return move.id;
    }
    if (typeof move === "number") {
        return move;
    }
    return null;
}

/**
 * ID backend de la orden; en la reimpresión la orden ya viene del servidor.
 */
export function getOrderServerId(order) {
    return order?.server_id || order?.backendId || null;
}

/**
 * Arma `props.data` completo de OrderReceipt: base del front + datos del
 * servidor + CFE + voucher OCA (COPIA CLIENTE).
 *
 * @param {Object} env - env de Owl (usa services.orm).
 * @param {Object} order - orden POS a imprimir.
 * @param {Object} [extra] - claves que se agregan a los datos (p. ej. isBill).
 */
export async function buildReceiptPrintData(env, order, extra = {}) {
    const orm = env.services.orm;
    const orderRef = order.pos_reference || order.name || "";
    const orderServerId = getOrderServerId(order);
    const accountMoveId = getAccountMoveId(order);

    let ocaVouchers = [];
    try {
        const rawVouchers = await orm.call("pos.order", "get_oca_voucher_dict_for_pos_receipt", [
            orderServerId || false,
            orderRef || false,
        ]);
        ocaVouchers = Array.isArray(rawVouchers)
            ? rawVouchers
            : (rawVouchers && typeof rawVouchers === "object" && Object.keys(rawVouchers).length
                ? [rawVouchers]
                : []);
    } catch (e) {
        console.warn(`${OCA_VOUCHER_LOG} buildReceiptPrintData voucher RPC error`, e);
    }

    let receiptServerData = null;
    try {
        receiptServerData = await orm.call(
            "pos.order",
            "get_receipt_data_from_invoice_or_order",
            [[], accountMoveId, orderRef, orderServerId]
        );
    } catch (e) {
        console.error(`${LOG} buildReceiptPrintData receiptServerData RPC error`, e);
    }

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
            }
        } catch (e) {
            console.error(`${LOG} buildReceiptPrintData cfe_data RPC error`, e);
        }
    }

    const base = order.export_for_printing();
    const receiptData = {
        ...base,
        ...(receiptServerData || {}),
        ...extra,
        oca_voucher: ocaVouchers[0] || {},
        oca_vouchers: ocaVouchers,
        cfe_data: cfeData,
        _skipAsyncReload: true,
    };
    if (!receiptServerData?.orderlines?.length) {
        receiptData.orderlines = base.orderlines;
    }
    if (!receiptServerData?.paymentlines?.length) {
        receiptData.paymentlines = base.paymentlines;
    }
    return receiptData;
}
