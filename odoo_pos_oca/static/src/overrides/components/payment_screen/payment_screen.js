/** @odoo-module */

import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import {patch} from "@web/core/utils/patch";
import {onMounted} from "@odoo/owl";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);

        onMounted(() => {
            // Si la caja se recargó con un cobro OCA en espera, la línea vuelve con su
            // transacción pero nadie la seguía esperando: quedaba trabada y la cajera
            // terminaba cobrando por el POS de respaldo. Se retoma la consulta del
            // resultado (Forum, 2026-11-20).
            for (const line of this.currentOrder?.paymentlines || []) {
                if (line.payment_method?.use_payment_terminal === "oca") {
                    line.payment_method.payment_terminal?.retomarCobroPendiente?.(line);
                }
            }
        });
    },
});
