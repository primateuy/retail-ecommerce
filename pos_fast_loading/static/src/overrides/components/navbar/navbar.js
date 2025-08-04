/** @odoo-module **/

import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { SynchNotificationWidget } from "@pos_fast_loading/app/SynchNotificationWidget/SynchNotificationWidget"

patch(Navbar, {
    components: { ...Navbar.components, SynchNotificationWidget },
});