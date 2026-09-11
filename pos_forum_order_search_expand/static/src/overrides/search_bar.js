/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { SearchBar } from "@point_of_sale/app/screens/ticket_screen/search_bar/search_bar";
import { normalizeScannedOrderReference } from "@pos_forum_order_search_expand/utils/order_reference";

patch(SearchBar.prototype, {
    /**
     * Normaliza el nº de orden escaneado antes de disparar la búsqueda.
     *
     * El input del buscador está autofocuseado al abrir la pantalla de órdenes y
     * barcode_service ignora los targets editables, así que la lectura del
     * ticket de cambio se teclea tal cual en el campo y el Enter final del
     * lector cae acá. Se reescribe también state.searchInput para que el cajero
     * vea la referencia real y no el crudo con apóstrofes.
     */
    _onClickSearchField(fieldName) {
        this.state.searchInput = normalizeScannedOrderReference(this.state.searchInput);
        return super._onClickSearchField(...arguments);
    },
});
