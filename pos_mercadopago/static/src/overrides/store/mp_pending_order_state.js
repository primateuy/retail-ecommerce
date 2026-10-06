/** @odoo-module **/

import { Order, Payment } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

function normalizePendingData(data) {
    if (!data || !data.orderReference || !data.qrSrc) {
        return null;
    }
    return {
        orderReference: data.orderReference,
        qrSrc: data.qrSrc,
        qrType: data.qrType || null,
    };
}

function getPendingOrderTimestamp(order) {
    if (!order) {
        return 0;
    }
    if (order.date_order?.toMillis) {
        return order.date_order.toMillis();
    }
    return order.sequence_number || 0;
}

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.mp_pending_order = this.mp_pending_order || null;
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.mp_pending_order = normalizePendingData(json.mp_pending_order);
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this.mp_pending_order) {
            json.mp_pending_order = { ...this.mp_pending_order };
        }
        return json;
    },

    setMpPendingOrder(data) {
        this.mp_pending_order = normalizePendingData(data);
        this.save_to_db();
    },

    clearMpPendingOrder() {
        this.mp_pending_order = null;
        this.save_to_db();
    },

    /**
     * Permite agregar otros medios de pago mientras la línea de MP no se envió.
     *
     * El core bloquea nuevas líneas si hay una electrónica sin terminar, y la de
     * MP queda en 'pending'/'retry' hasta que se confirma el QR. Una vez
     * generado el QR se sigue bloqueando, porque cambiar montos ahí descuadra
     * lo cobrado con el pedido.
     */
    electronic_payment_in_progress() {
        if (this.mp_pending_order) {
            return super.electronic_payment_in_progress(...arguments);
        }
        return this.get_paymentlines().some((line) => {
            const status = line.payment_status;
            if (!status || ["done", "reversed"].includes(status)) {
                return false;
            }
            const isMercadoPago = line.payment_method.use_payment_terminal === "mercado_pago";
            return !(isMercadoPago && ["pending", "retry"].includes(status));
        });
    },

    /**
     * Propone como monto de la nueva línea el saldo real de la orden.
     *
     * El core usa get_due(), que solo descuenta líneas en 'done'; como se permite
     * agregar medios con MP en 'pending'/'retry', la nueva línea tomaba el total
     * sin descontar lo asignado a MP. get_due() no se cambia porque el core lo usa
     * para decidir si la orden está paga al validar.
     *
     * @param {Object} payment_method método de pago de la nueva línea.
     * @returns {Payment|false} la línea creada, o false si el core no la agregó.
     */
    add_paymentline(payment_method) {
        const newLine = super.add_paymentline(...arguments);
        if (!newLine) {
            return newLine;
        }
        // Se compara por cid: get_paymentlines() devuelve proxies reactivos, distintos
        // por referencia de newLine aunque sean la misma línea.
        const pendingMpAmount = this.get_paymentlines()
            .filter(
                (line) =>
                    line.cid !== newLine.cid &&
                    line.payment_method.use_payment_terminal === "mercado_pago" &&
                    ["pending", "retry"].includes(line.payment_status)
            )
            .reduce((sum, line) => sum + line.get_amount(), 0);
        if (pendingMpAmount) {
            newLine.set_amount(Math.max(newLine.get_amount() - pendingMpAmount, 0));
        }
        return newLine;
    },
});

patch(Payment.prototype, {
    /**
     * Ajusta el estado de la línea de MP después de "Enviar".
     *
     * El envío solo genera el QR; el pago se confirma después con "Comprobar
     * pago". El core marca 'retry' ("Transacción cancelada") ante cualquier
     * respuesta no exitosa, así que para MP se usa:
     * - 'waitingCapture' ("Solicitud enviada") si el QR quedó generado;
     * - 'pending' ("Enviar") si no se generó (validación o error).
     */
    handle_payment_response(isPaymentSuccessful) {
        if (
            isPaymentSuccessful ||
            this.payment_method.use_payment_terminal !== "mercado_pago"
        ) {
            return super.handle_payment_response(...arguments);
        }
        this.set_payment_status(this.order?.mp_pending_order ? "waitingCapture" : "pending");
        return false;
    },
});

patch(PosStore.prototype, {
    _syncMercadoPagoPanelWithOrder(order = this.get_order()) {
        const data = normalizePendingData(order?.mp_pending_order);
        this.mpQrPanel = data ? { ...data } : null;
        return this.mpQrPanel;
    },

    _getPendingMercadoPagoOrders() {
        return [...this.get_order_list()].filter((order) =>
            normalizePendingData(order?.mp_pending_order)
        );
    },

    _selectPendingMercadoPagoOrder() {
        const pendingOrders = this._getPendingMercadoPagoOrders().sort(
            (left, right) => getPendingOrderTimestamp(right) - getPendingOrderTimestamp(left)
        );
        const targetOrder = pendingOrders[0] || null;
        if (targetOrder) {
            this.set_order(targetOrder);
        }
        return targetOrder;
    },

    async after_load_server_data() {
        await super.after_load_server_data(...arguments);
        this._selectPendingMercadoPagoOrder();
        this._syncMercadoPagoPanelWithOrder();
    },

    set_order(order) {
        super.set_order(...arguments);
        this._syncMercadoPagoPanelWithOrder(order);
    },

    add_new_order() {
        const order = super.add_new_order(...arguments);
        this._syncMercadoPagoPanelWithOrder(order);
        return order;
    },
});
