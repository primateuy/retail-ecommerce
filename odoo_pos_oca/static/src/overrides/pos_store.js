/** @odoo-module */

import {PosStore} from "@point_of_sale/app/store/pos_store";
import {patch} from "@web/core/utils/patch";
import {_t} from "@web/core/l10n/translation";
import {ocaOrdenBloqueada} from "@odoo_pos_oca/app/oca_bloqueo";

patch(PosStore.prototype, {
    // La orden se modifica en la pantalla de productos. Con un cobro OCA en curso o aprobado
    // no se entra ahí: se queda en la de pago, que retoma el cobro. Cubre la recarga de la
    // caja (que abre la pantalla de productos), el botón «volver» y cualquier otro camino
    // (Forum, 2026-11-20).
    showScreen(name, props) {
        if (name === "ProductScreen" && ocaOrdenBloqueada(this.get_order())) {
            this.env.services.notification?.add(
                _t("Esta orden tiene un cobro con tarjeta en curso o aprobado: no se puede modificar."),
                {type: "warning"}
            );
            return super.showScreen("PaymentScreen");
        }
        return super.showScreen(...arguments);
    },
});
