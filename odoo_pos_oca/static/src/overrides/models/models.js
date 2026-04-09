/** @odoo-module */
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { Payment } from "@point_of_sale/app/store/models";
import { PaymentOCA } from "@odoo_pos_oca/app/payment_oca";
import { patch } from "@web/core/utils/patch";

register_payment_method("oca", PaymentOCA);

patch(Payment.prototype, {
    setup() {
        super.setup(...arguments);
    },
    //@override
    export_as_JSON() {
        // Bloque: persistir el TransactionId OCA en el backend (pos.payment.transaction_id)
        // para que _associate_oca_transactions enlace por referencia y no por monto
        // cuando hay varios pagos parciales del mismo importe.
        const json = super.export_as_JSON(...arguments);
        if (this.transaction_id !== undefined && this.transaction_id !== false && this.transaction_id !== null) {
            json.transaction_id = this.transaction_id;
        }
        return json;
    },
    //@override
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        if (json && json.transaction_id !== undefined && json.transaction_id !== false) {
            this.transaction_id = json.transaction_id;
        }
    },
});
