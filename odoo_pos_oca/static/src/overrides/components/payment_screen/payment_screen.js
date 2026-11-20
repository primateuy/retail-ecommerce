/** @odoo-module */

import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import {patch} from "@web/core/utils/patch";
import {onMounted} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";
import {ocaOrdenBloqueada} from "@odoo_pos_oca/app/oca_bloqueo";

patch(PaymentScreen.prototype, {
    // Cambiar el cliente vuelve a calcular precios y promociones (cambio_precio, cumpleaños):
    // con un cobro OCA en curso o aprobado el total ya no coincidiría con lo cobrado. Se deja
    // completar los datos del mismo cliente y elegir uno si la orden no tenía (Forum, 2026-11-20).
    async selectPartner(isEditMode = false, missingFields = []) {
        if (!isEditMode && this.currentOrder?.get_partner() && ocaOrdenBloqueada(this.currentOrder)) {
            this.env.services.notification?.add(
                _t("Esta orden tiene un cobro con tarjeta en curso o aprobado: no se puede cambiar el cliente."),
                {type: "warning"}
            );
            return;
        }
        return super.selectPartner(...arguments);
    },

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
