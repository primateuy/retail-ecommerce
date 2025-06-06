/** @odoo-module */

import {patch} from "@web/core/utils/patch";
import {PosBus} from "@point_of_sale/app/bus/pos_bus_service";

patch(PosBus.prototype, {
    // Override
    dispatch(message) {
        super.dispatch(...arguments);

        if (message.type === "OCA_LATEST_RESPONSE") {
            console.log('OCA_LATEST_RESPONSE', message);
            var payload = message.payload;
            var id_config = payload.id_config;
            if (id_config === this.pos.config.id) {
                const pendingLine = this.pos.getPendingPaymentLine("oca");
                console.log('BUS OCA_LATEST_RESPONSE', payload);
                if (pendingLine) {
                    pendingLine.payment_method.payment_terminal.handleOCAStatusResponse(payload);
                }
            }
        }
    },
});
