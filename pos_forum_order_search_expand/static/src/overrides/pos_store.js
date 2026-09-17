/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ALL_SEARCH_FIELD } from "@pos_forum_order_search_expand/utils/search_fields";

patch(PosStore.prototype, {
    /**
     * Abre el buscador de órdenes en "Todo" en vez de "Nº de recibo".
     *
     * Es el searchDetails con el que arranca la pantalla de órdenes cuando se
     * entra desde el botón Órdenes; el cajero puede teclear un cliente, un nº
     * de orden o escanear el ticket de cambio sin cambiar de campo.
     */
    getDefaultSearchDetails() {
        return {
            ...super.getDefaultSearchDetails(...arguments),
            fieldName: ALL_SEARCH_FIELD,
        };
    },
});
