/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { ReprintChangeTicketButton } from "@pos_forum_order_search_expand/components/reprint_change_ticket_button";
import { formatOrderReferenceSearch } from "@pos_forum_order_search_expand/utils/order_reference";

patch(TicketScreen, {
    components: {
        ...TicketScreen.components,
        ReprintChangeTicketButton,
    },
});

patch(TicketScreen.prototype, {
    /**
     * Hace que la búsqueda por nº de recibo tolere lo que emite la lectora.
     *
     * _computeSyncedOrdersDomain arma el dominio con ilike '%término%', así que
     * alcanza con la parte numérica: buscando sin el prefijo el match no depende
     * del idioma con el que el PDV generó pos_reference ("Orden ..." en las
     * órdenes de acá, "Order ..." si alguna sesión corrió en inglés).
     */
    _getSearchFields() {
        const fields = super._getSearchFields(...arguments);
        if (fields.RECEIPT_NUMBER) {
            fields.RECEIPT_NUMBER.formatSearch = formatOrderReferenceSearch;
        }
        return fields;
    },
});
