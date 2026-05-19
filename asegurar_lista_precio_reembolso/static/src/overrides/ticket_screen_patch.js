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
 * Bloquea cambios de pricelist sobre órdenes de reembolso marcadas. El lock
 * es absoluto: cubre el botón manual, la cascada de set_partner del core y
 * tambien las llamadas con _restoringPricelist=true de cambio_precio. Sin
 * esa segunda cobertura, _restoreOriginalPricelist de cambio_precio pisa la
 * pricelist heredada cuando las qty del refund son negativas y el reward
 * pricelist_change deja de cumplir las reglas. En refund la heredada manda.
 */
patch(Order.prototype, {
    setup() {
        super.setup?.(...arguments);
        if (this._refundPricelistLocked === undefined) {
            this._refundPricelistLocked = false;
        }
    },
    init_from_JSON(json) {
        const ret = super.init_from_JSON(...arguments);
        if (json && json._refundPricelistLocked) {
            this._refundPricelistLocked = true;
        }
        return ret;
    },
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this._refundPricelistLocked) {
            json._refundPricelistLocked = true;
        }
        return json;
    },
    set_pricelist(pricelist) {
        if (this._refundPricelistLocked) {
            return;
        }
        return super.set_pricelist(...arguments);
    },
});
