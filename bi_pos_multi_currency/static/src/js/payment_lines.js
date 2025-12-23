/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
import { usePos } from "@point_of_sale/app/store/pos_hook";

patch(PaymentScreenPaymentLines.prototype, {
    setup() {
        super.setup();
        this.pos=usePos();
    },

    formatLineAmount(paymentline) {
        if(paymentline.currency_amount_pay > 0){
            return paymentline.currency_amount_pay;
        }else{
            return this.env.utils.formatCurrency(paymentline.get_amount(), false);
        }
    }
});