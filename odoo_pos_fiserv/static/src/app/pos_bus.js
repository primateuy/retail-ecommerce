/** @odoo-module */

import {patch} from "@web/core/utils/patch";
import {PosBus} from "@point_of_sale/app/bus/pos_bus_service";

patch(PosBus.prototype, {
    dispatch(message) {
        super.dispatch(...arguments);

        if (message.type === "FISERV_LATEST_RESPONSE") {
            const payload = message.payload;
            const id_config = payload.id_config;
            if (id_config === this.pos.config.id) {
                const pendingLine = this.pos.getPendingPaymentLine("fiserv");
                if (pendingLine) {
                    pendingLine.payment_method.payment_terminal.handleFiservStatusResponse(payload);
                }
            }
        }
    },
});
