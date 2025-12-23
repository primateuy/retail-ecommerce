/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

patch(PosStore.prototype, {

    async _processData(loadedData) {
        await super._processData(loadedData);
        this._loadProductPricelistItem(loadedData['product.pricelist.item'])
        this._loadCurrency(loadedData['currencies'])
    },

    _loadProductPricelistItem(pricelist_items){
        var self = this;
        self.pricelist_items = pricelist_items;
        var pricelist_by_id = {};

        self.pricelists.forEach(function (pricelist) {
            pricelist_by_id[pricelist.id] = pricelist;
        });

        pricelist_items.forEach(function (item) {
            var pricelist = pricelist_by_id[item.pricelist_id[0]];
            pricelist.items.push(item);
            item.base_pricelist = pricelist_by_id[item.base_pricelist_id[0]];
        });
    },

    _loadCurrency(currencies){
        var self = this;
        if (this.selectedOrder){
            self.currency = this.selectedOrder.pricelist.currency_id;
            
        }else{

            self.currency = currencies[0]   ;
        }
        self.company_currency = currencies[1];
        for (var i = 0; i < currencies.length; i++) {
            if(currencies[i].id == self.config.currency_id[0]){
                self.currency = currencies[i];
                break;
            }
        }
        for (var i = 0; i < currencies.length; i++) {
            if(currencies[i].id == self.company.currency_id[0]){
                self.company_currency = currencies[i];
                break;
            }
        }
        self.currency['decimals'] = 2;
        if (self.currency.rounding > 0 && self.currency.rounding < 1) {
            self.currency.decimals = Math.ceil(Math.log(1.0 / self.currency.rounding) / Math.log(10));
        } else {
            self.currency.decimals = 0;
        }
        var config_currency = self.config.currency_id[0];
        var config_id = self.config.id;
        self.currencies = currencies;
    },
    
});