/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

/**
 * Al crear un reembolso desde el POS, la orden destino hereda la lista de
 * precio de la orden original. El hook addAdditionalRefundInfo se ejecuta
 * al final del loop de creación, una vez que el partner ya fue asignado
 * (evitando que set_partner sobreescriba la lista de precio).
 */
patch(TicketScreen.prototype, {
    async addAdditionalRefundInfo(order, destinationOrder) {
        const result = await super.addAdditionalRefundInfo(...arguments);
        if (order.pricelist) {
            destinationOrder.set_pricelist(order.pricelist);
        }
        return result;
    },
});
