/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

/**
 * Al crear un reembolso desde el POS, la orden destino hereda la lista de
 * precio de la orden original. El hook addAdditionalRefundInfo se ejecuta
 * al final del loop de creación, una vez que el partner ya fue asignado
 * (evitando que set_partner sobreescriba la lista de precio).
 *
 * Si la lista heredada NO es la default del POS, se marca la orden como
 * bloqueada y cualquier set_pricelist posterior queda neutralizado. Si la
 * heredada sí es la default, no se marca y el cajero puede cambiar libre.
 */
patch(TicketScreen.prototype, {
    async addAdditionalRefundInfo(order, destinationOrder) {
        const result = await super.addAdditionalRefundInfo(...arguments);
        if (order.pricelist) {
            destinationOrder.set_pricelist(order.pricelist);
            const defaultPricelistId = this.pos?.default_pricelist?.id;
            if (defaultPricelistId && order.pricelist.id !== defaultPricelistId) {
                destinationOrder._refundPricelistLocked = true;
            }
        }
        return result;
    },
});

/**
 * Bloquea cambios de pricelist sobre órdenes de reembolso marcadas. Cubre
 * el botón manual de listas y el cambio en cascada disparado por
 * set_partner del core. _restoringPricelist (cambio_precio) marca llamadas
 * internas del sistema (recompensas de lealtad) que sí deben pasar.
 */
patch(Order.prototype, {
    set_pricelist(pricelist) {
        if (this._refundPricelistLocked && !this._restoringPricelist) {
            return;
        }
        return super.set_pricelist(...arguments);
    },
});
