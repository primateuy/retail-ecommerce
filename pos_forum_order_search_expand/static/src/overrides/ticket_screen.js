/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { ReprintChangeTicketButton } from "@pos_forum_order_search_expand/components/reprint_change_ticket_button";

patch(TicketScreen, {
    components: {
        ...TicketScreen.components,
        ReprintChangeTicketButton,
    },
});
