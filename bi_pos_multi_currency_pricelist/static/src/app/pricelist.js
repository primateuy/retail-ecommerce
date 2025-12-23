/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { SetPricelistButton } from "@point_of_sale/app/screens/product_screen/control_buttons/pricelist_button/pricelist_button";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";

patch(SetPricelistButton.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        this.popup = useService("popup");
    },

    async click() {
        // Create the list to be passed to the SelectionPopup.
        // Pricelist object is passed as item in the list because it
        // is the object that will be returned when the popup is confirmed.
        const selectionList = this.env.services.pos.pricelists.map(pricelist => ({
            id: pricelist.id,
            label: pricelist.name,
            isSelected: pricelist.id === this.currentOrder.pricelist.id,
            item: pricelist,
        }));

        const { confirmed, payload: selectedPricelist } = await this.popup.add(
            SelectionPopup,
            {
                title: _t('Select the pricelist'),
                list: selectionList,
            }
        );

        if (confirmed) {
            var order = this.currentOrder;
            var new_currency = {};
            for (var i = 0; i < this.env.services.pos.currencies.length; i++) {
                if(this.env.services.pos.currencies[i].id == selectedPricelist.currency_id[0]){
                    new_currency = this.env.services.pos.currencies[i];
                    break;
                }
            }
            if (new_currency.rounding > 0 && new_currency.rounding < 1) {
                new_currency.decimals = Math.ceil(Math.log(1.0 / new_currency.rounding) / Math.log(10));
            } else {
                new_currency.decimals = 0;
            }
            var converted_amount = new_currency['currency_convert'];
            this.env.services.pos.currency = new_currency;
            order.new_currency = new_currency;
            if (selectedPricelist){
                this.currentOrder.set_pricelist(selectedPricelist);
            }
        }
    },
    
});