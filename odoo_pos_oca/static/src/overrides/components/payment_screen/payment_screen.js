/** @odoo-module */

import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import {patch} from "@web/core/utils/patch";
import {onMounted} from "@odoo/owl";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        console.log('-----------------Payment Screen Setup------------------');

        onMounted(() => {
            console.log('-----------------Payment Screen onMounted------------------');

            // const pendingPaymentLine = this.currentOrder.paymentlines.find(
            //     (paymentLine) => paymentLine.payment_method.use_payment_terminal === "oca" && !paymentLine.is_done() && paymentLine.get_payment_status() !== "pending"
            // );
            //
            // if (pendingPaymentLine) {
            //     const oca_interface = pendingPaymentLine.payment_method.payment_terminal;
            //     pendingPaymentLine.set_payment_status('waiting');
            //     handy_interface.start_get_status_polling().then(isPaymentSuccessful => {
            //         if (isPaymentSuccessful) {
            //             pendingPaymentLine.set_payment_status('done');
            //             pendingPaymentLine.can_be_reversed = handy_interface.supports_reversals;
            //         } else {
            //             pendingPaymentLine.set_payment_status('retry');
            //         }
            //     });
            // }
        });
    },
});
