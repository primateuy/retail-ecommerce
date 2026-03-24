/** @odoo-module */

/**
 * Extiende el modelo Payment del POS con datos de transacción manual.
 *
 * Almacena los valores capturados en el popup dinámico para enviarlos al
 * backend junto con el pedido POS.
 */

import { Payment } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(Payment.prototype, {
    /**
     * Inicializa valores manuales en líneas nuevas o restaura desde JSON.
     */
    setup(_defaultObj, options) {
        super.setup(...arguments);
        if (!options || !options.json) {
            this.manual_payment_values = {};
        }
    },

    /**
     * Asigna el diccionario de valores capturados en el popup manual.
     */
    set_manual_payment_values(values) {
        this.manual_payment_values = values || {};
    },

    /**
     * Retorna los valores de transacción manual asociados a la línea.
     */
    get_manual_payment_values() {
        return this.manual_payment_values || {};
    },

    /**
     * Restaura valores desde JSON al cargar el pedido.
     */
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.manual_payment_values = json.manual_payment_values || {};
    },

    /**
     * Serializa valores manuales para envío al servidor.
     */
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.manual_payment_values = this.manual_payment_values || {};
        return json;
    },
});
