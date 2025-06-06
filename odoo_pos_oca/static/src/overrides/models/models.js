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
        const json = super.export_as_JSON(...arguments);
        return json;
    },
    //@override
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
    },
});
