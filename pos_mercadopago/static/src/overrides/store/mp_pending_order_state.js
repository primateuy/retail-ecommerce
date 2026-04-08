/** @odoo-module **/

import { Order } from "@point_of_sale/app/store/models";
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
