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
        // odoo_pos_oca_promociones envía OCA_LATEST_RESPONSE aunque el método POS sea Fiserv ITD
        // (mismo hilo ITD / Query). Sin esto el POS queda en «Esperando la tarjeta».
        if (message.type === "OCA_LATEST_RESPONSE") {
            const payload = message.payload;
            const id_config = payload?.id_config;
            if (id_config === this.pos.config.id) {
                const pendingFiserv = this.pos.getPendingPaymentLine("fiserv");
                if (pendingFiserv) {
                    pendingFiserv.payment_method.payment_terminal.handleFiservStatusResponse(
                        payload
                    );
                }
            }
        }
    },
});
