/** @odoo-module */
/*
 * Enruta GETNET_LATEST_RESPONSE (emitido por el worker del server en el
 * canal de la sesión) hacia la interfaz de pago Getnet, filtrando por
 * config para no cruzar cajas.
 */
import {patch} from "@web/core/utils/patch";
import {PosBus} from "@point_of_sale/app/bus/pos_bus_service";

patch(PosBus.prototype, {
    dispatch(message) {
        super.dispatch(...arguments);
        if (message.type === "GETNET_LATEST_RESPONSE") {
            const payload = message.payload;
            if (payload.id_config !== this.pos.config.id) {
                return;
            }
            const line = this.pos.getPendingPaymentLine("getnet");
            const paymentTerminal =
                line?.payment_method?.payment_terminal;
            if (paymentTerminal?.handleGetnetStatusResponse) {
                paymentTerminal.handleGetnetStatusResponse(payload);
            }
        }
    },
});
