/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { ReprintChangeTicketButton } from "@pos_forum_order_search_expand/components/reprint_change_ticket_button";
import {
    formatOrderReferenceSearch,
    parseOrderReference,
} from "@pos_forum_order_search_expand/utils/order_reference";
import { ALL_SEARCH_FIELD } from "@pos_forum_order_search_expand/utils/search_fields";

// Campos de pos.order que cubre la búsqueda "Todo". La fecha queda afuera
// porque su formatSearch parsea el término y un texto libre no es una fecha.
const ALL_SEARCH_MODEL_FIELDS = ["tracking_number", "pos_reference", "partner_id.complete_name"];

patch(TicketScreen, {
    components: {
        ...TicketScreen.components,
        ReprintChangeTicketButton,
    },
});

patch(TicketScreen.prototype, {
    /**
     * Agrega el campo "Todo" y hace que el nº de recibo tolere la lectora.
     *
     * "Todo" va primero: cuando la pantalla se abre sin searchDetails (botón
     * Reembolso con una orden sin cliente) la SearchBar cae en el primer campo
     * de la lista, y así el cajero busca por nº de orden, nº de recibo o
     * cliente sin tener que elegir.
     *
     * Para RECEIPT_NUMBER, _computeSyncedOrdersDomain arma el dominio con ilike
     * '%término%', así que alcanza con la parte numérica: buscando sin el
     * prefijo el match no depende del idioma con el que el PDV generó
     * pos_reference ("Orden ..." en las órdenes de acá, "Order ..." si alguna
     * sesión corrió en inglés).
     */
    _getSearchFields() {
        const fields = super._getSearchFields(...arguments);
        if (fields.RECEIPT_NUMBER) {
            fields.RECEIPT_NUMBER.formatSearch = formatOrderReferenceSearch;
        }
        return {
            [ALL_SEARCH_FIELD]: {
                repr: (order) =>
                    [order.trackingNumber, order.name, order.get_partner_name()]
                        .filter(Boolean)
                        .join(" "),
                displayName: _t("All"),
                modelField: null,
            },
            ...fields,
        };
    },

    /**
     * Dominio de órdenes sincronizadas para "Todo" y para códigos escaneados.
     *
     * Si el término tiene forma de nº de orden se busca siempre contra
     * pos_reference, sin importar el campo activo: cubre el caso en que
     * searchDetails llega ya armado (p. ej. desde Reembolso con el cliente
     * precargado) y la SearchBar no pasó por _onClickSearchField.
     *
     * Para "Todo" se arma un OR sobre los campos de ALL_SEARCH_MODEL_FIELDS;
     * search_paid_order_ids lo combina con AND al dominio base, así que el
     * filtro de estado sigue aplicando.
     */
    _computeSyncedOrdersDomain() {
        const { fieldName, searchTerm } = this._state.ui.searchDetails;
        const term = (searchTerm || "").trim();
        if (!term) {
            return super._computeSyncedOrdersDomain(...arguments);
        }
        const reference = parseOrderReference(term);
        if (reference) {
            return [["pos_reference", "ilike", `%${reference}%`]];
        }
        if (fieldName !== ALL_SEARCH_FIELD) {
            return super._computeSyncedOrdersDomain(...arguments);
        }
        const leaves = ALL_SEARCH_MODEL_FIELDS.map((field) => [field, "ilike", `%${term}%`]);
        return [...Array(leaves.length - 1).fill("|"), ...leaves];
    },
});
