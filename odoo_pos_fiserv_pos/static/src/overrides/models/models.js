/** @odoo-module */

import {register_payment_method} from "@point_of_sale/app/store/pos_store";
import {Payment} from "@point_of_sale/app/store/models";
import {PaymentFiserv} from "@odoo_pos_fiserv/app/payment_fiserv";
import {patch} from "@web/core/utils/patch";

register_payment_method("fiserv", PaymentFiserv);

patch(Payment.prototype, {
    setup() {
        super.setup(...arguments);
    },
    export_as_JSON() {
        return super.export_as_JSON(...arguments);
    },
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
    },
});
