/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { SearchBar } from "@point_of_sale/app/screens/ticket_screen/search_bar/search_bar";
import {
    normalizeScannedOrderReference,
    parseOrderReference,
} from "@pos_forum_order_search_expand/utils/order_reference";

const RECEIPT_NUMBER_FIELD = "RECEIPT_NUMBER";

patch(SearchBar.prototype, {
    /**
     * Normaliza el nº de orden escaneado y fuerza la búsqueda por nº de recibo.
     *
     * El input del buscador está autofocuseado al abrir la pantalla de órdenes y
     * barcode_service ignora los targets editables, así que la lectura del
     * ticket de cambio se teclea tal cual en el campo y el Enter final del
     * lector cae acá. Se reescribe state.searchInput para que el cajero vea la
     * referencia real y no el crudo con apóstrofes (ni el nombre de cliente que
     * el botón Reembolso deja precargado).
     *
     * El campo seleccionado depende de cómo se abrió la pantalla: desde Órdenes
     * es "Todo", pero desde Reembolso el core la abre en "Cliente" con el nombre
     * del cliente actual. Si lo tecleado tiene forma de nº de orden se cambia el
     * campo a "Nº de recibo", que es el único que sabe buscarlo, sin importar
     * cuál estuviera activo.
     */
    _onClickSearchField(fieldName) {
        if (parseOrderReference(this.state.searchInput)) {
            this.state.searchInput = normalizeScannedOrderReference(this.state.searchInput);
            const receiptFieldId = this.searchFieldsList.indexOf(RECEIPT_NUMBER_FIELD);
            if (receiptFieldId !== -1) {
                this.state.selectedSearchFieldId = receiptFieldId;
                fieldName = RECEIPT_NUMBER_FIELD;
            }
        }
        return super._onClickSearchField(fieldName);
    },
});
