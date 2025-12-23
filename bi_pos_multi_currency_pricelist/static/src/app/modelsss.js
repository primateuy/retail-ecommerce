/** @odoo-module */

import { Order, Orderline, Payment , Product } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
const { DateTime } = luxon;
import { deserializeDate } from "@web/core/l10n/dates";
import {
    formatFloat,
    roundDecimals as round_di,
    roundPrecision as round_pr,
    floatIsZero,
} from "@web/core/utils/numbers";

// New orders are now associated with the current table, if any.
patch(Product.prototype, {
    setup(_defaultObj, options) {
        super.setup(...arguments);
    },

    get_price(pricelist, quantity, price_extra = 0, recurring = false) {
        if (pricelist){

            const date = DateTime.now();
            var self = this
            var amount = pricelist.currency_convert
            // In case of nested pricelists, it is necessary that all pricelists are made available in
            // the POS. Display a basic alert to the user in the case where there is a pricelist item
            // but we can't load the base pricelist to get the price when calling this method again.
            // As this method is also call without pricelist available in the POS, we can't just check
            // the absence of pricelist.
            if (recurring && !pricelist) {
                alert(
                    _t(
                        "An error occurred when loading product prices. " +
                            "Make sure all pricelists are available in the POS."
                    )
                );
            }
            var category_ids = [];
            var get_rates = {};
            var category = this.categ;
            while (category) {
                category_ids.push(category.id);
                category = category.parent;
            }
            var pricelist_items = (this.applicablePricelistItems[pricelist.id] || []).filter(function (item) {
                    const categories = self.parent_category_ids.concat(self.categ.id);
                    return (!item.categ_id || categories.includes(item.categ_id[0])) &&
                    (!item.date_start || deserializeDate(item.date_start) <= date) &&
                    (!item.date_end || deserializeDate(item.date_end) >= date);
                    });
            let price = this.lst_price + (price_extra || 0);
            var pricelist_currency = pricelist.currency_id[0];
            if(this.pos.config.currency_id[0] != pricelist_currency)
            {
                var new_rate = price;
                if(amount !=0){
                    new_rate = (amount * price);
                }
                price =  new_rate;
            }
            pricelist_items.find( function (rule) {
                if (rule.min_quantity && quantity < rule.min_quantity) {
                    return false;
                }

                if (rule.base === 'pricelist' && rule.base_pricelist_id){
                    price = self.get_price(rule.base_pricelist, quantity);
                    $.each(self.pos.currencies, function (line) {
                        if (line.id == rule.currency_id[0]){
                            get_rates[line.id] = line.rate; 
                        }
                        if (line.id == rule.base_pricelist.currency_id[0]){
                            get_rates[line.id] = line.rate;
                        }
                        if (get_rates[rule.currency_id[0]] != undefined){
                            var res = get_rates[rule.currency_id[0]] / get_rates[rule.base_pricelist.currency_id[0]];
                            price = price * res;
                        }
                    });
                    }else if (rule.base === "pricelist") {
                        const base_pricelist = this.pos.pricelists.find(
                            (pricelist) => pricelist.id === rule.base_pricelist_id[0]
                        );
                        if (base_pricelist) {
                            price = this.get_price(base_pricelist, quantity, 0, true);
                        }
                    } else if (rule.base === "standard_price") {
                        price = this.standard_price;
                    }

                    if (rule.compute_price === "fixed") {
                        price = rule.fixed_price;
                    } else if (rule.compute_price === "percentage") {
                        price = price - price * (rule.percent_price / 100);
                    } else {
                        var price_limit = price;
                        price -= price * (rule.price_discount / 100);
                        if (rule.price_round) {
                            price = round_pr(price, rule.price_round);
                        }
                        if (rule.price_surcharge) {
                            price += rule.price_surcharge;
                        }
                        if (rule.price_min_margin) {
                            price = Math.max(price, price_limit + rule.price_min_margin);
                        }
                        if (rule.price_max_margin) {
                            price = Math.min(price, price_limit + rule.price_max_margin);
                        }
                    }

            // This return value has to be rounded with round_di before
            // being used further. Note that this cannot happen here,
            // because it would cause inconsistencies with the backend for
            // pricelist that have base == 'pricelist'.
                })  ;
            return price;
        }else{
            const date = DateTime.now();

        // In case of nested pricelists, it is necessary that all pricelists are made available in
        // the POS. Display a basic alert to the user in the case where there is a pricelist item
        // but we can't load the base pricelist to get the price when calling this method again.
        // As this method is also call without pricelist available in the POS, we can't just check
        // the absence of pricelist.
        if (recurring && !pricelist) {
            alert(
                _t(
                    "An error occurred when loading product prices. " +
                        "Make sure all pricelists are available in the POS."
                )
            );
        }

        const rules = !pricelist
            ? []
            : (this.applicablePricelistItems[pricelist.id] || []).filter((item) =>
                  this.isPricelistItemUsable(item, date)
              );

        let price = this.lst_price + (price_extra || 0);
        const rule = rules.find((rule) => !rule.min_quantity || quantity >= rule.min_quantity);
        if (!rule) {
            return price;
        }

        if (rule.base === "pricelist") {
            const base_pricelist = this.pos.pricelists.find(
                (pricelist) => pricelist.id === rule.base_pricelist_id[0]
            );
            if (base_pricelist) {
                price = this.get_price(base_pricelist, quantity, 0, true);
            }
        } else if (rule.base === "standard_price") {
            price = this.standard_price;
        }

        if (rule.compute_price === "fixed") {
            price = rule.fixed_price;
        } else if (rule.compute_price === "percentage") {
            price = price - price * (rule.percent_price / 100);
        } else {
            var price_limit = price;
            price -= price * (rule.price_discount / 100);
            if (rule.price_round) {
                price = round_pr(price, rule.price_round);
            }
            if (rule.price_surcharge) {
                price += rule.price_surcharge;
            }
            if (rule.price_min_margin) {
                price = Math.max(price, price_limit + rule.price_min_margin);
            }
            if (rule.price_max_margin) {
                price = Math.min(price, price_limit + rule.price_max_margin);
            }
        }

        // This return value has to be rounded with round_di before
        // being used further. Note that this cannot happen here,
        // because it would cause inconsistencies with the backend for
        // pricelist that have base == 'pricelist'.
        return price;
        }

    },


});



patch(Orderline.prototype, {
    get_tax() {
        var total_tax = this.get_all_prices().tax;
        var converted_tax = total_tax;
        if (this.pos.selectedOrder){

            var currency = this.pos.selectedOrder.pricelist;
        }else{
            var currency =  this.pos.currency
        }

        if (this.pos.mainScreen.component){
            if (this.pos.mainScreen.component.name == 'TicketScreen'){
                if(currency){
                    converted_tax = total_tax * currency.currency_convert;
                }
            }else{
               converted_tax = total_tax
            }
        }
        return converted_tax;
    },

})

patch(Order.prototype, {
   setup(_defaultObj, options) {
        super.setup(...arguments);
        if (options.json) {
            for (var i = 0; i < this.pos.currencies.length; i++) {
                if (this.pos.default_pricelist){
                    if(this.pos.currencies[i].id == this.pos.default_pricelist.currency_id[0]){
                        this.pos.currency = this.pos.currencies[i];
                        break;
                    }
                }
            }
        }
    },

    // get_total_with_tax() {
    //     var amount = this.get_total_without_tax() + this.get_total_tax();
    //     let coverted_amount = 0;

    //     return coverted_amount;
    // },


    get_total_without_tax() {

        var amount = round_pr(
            this.orderlines.reduce(function (sum, orderLine) {
                return sum + orderLine.get_price_without_tax();
            }, 0),
            this.pos.currency.rounding
        );
        var currency = this.pos.currency;
        if (this.pos.selectedOrder){

            var currency = this.pos.selectedOrder.pricelist;
        }else{
            var currency =  this.pos.currency
        }
        let coverted_amount = 0;
        if (this.pos.mainScreen.component){
            if (this.pos.mainScreen.component.name == 'TicketScreen'){
                if(currency){
                    coverted_amount = amount * currency.currency_convert;
                }
            }else{
               coverted_amount = amount
            }
        }
        
        
        return coverted_amount;
    },

    
    // get_total_with_tax() {

    //     var self = this;
    //     var amount = this.get_total_without_tax() + this.get_total_tax();
    //     let all_curr = this.pos.currencies

    //     var currency = this.pos.currency;
    //     if (this.pos.selectedOrder){

    //         var currency = this.pos.selectedOrder.pricelist;
    //     }else{
    //         var currency =  this.pos.currency
    //     }
    //     let coverted_amount = 0;
    //     if (this.pos.mainScreen.component){
    //         if (this.pos.mainScreen.component.name == 'TicketScreen'){
    //             if(currency){
    //                 coverted_amount = amount * currency.currency_convert;
    //             }
    //         }else{
    //            coverted_amount = amount
    //         }
    //     }
        
        
    //     return coverted_amount;
    // },


   
    set_pricelist (pricelist) {
        var self = this;
        this.pricelist = pricelist;

        for (var i = 0; i < self.pos.currencies.length; i++) {
            if (pricelist){
                if(self.pos.currencies[i].id == pricelist.currency_id[0]){
                    self.pos.currency = self.pos.currencies[i];
                    break;
                }
            }
        }
        const lines_to_recompute = this.get_orderlines().filter(
            (line) =>
               !(line.comboLines?.length || line.comboParent)
        );
        lines_to_recompute.forEach((line) => {
            line.set_unit_price(
                line.product.get_price(self.pricelist, line.get_quantity(), line.get_price_extra())
            );
            self.fix_tax_included_price(line);
        });
        const combo_parent_lines = this.get_orderlines().filter(
            (line) => line.price_type === "original" && line.comboLines?.length
        );
        const attributes_prices = {};
        combo_parent_lines.forEach((parentLine) => {
            attributes_prices[parentLine.id] = this.compute_child_lines(
                parentLine.product,
                parentLine.comboLines.map((childLine) => {
                    const comboLineCopy = { ...childLine.comboLine };
                    if (childLine.attribute_value_ids) {
                        comboLineCopy.configuration = {
                            attribute_value_ids: childLine.attribute_value_ids,
                        };
                    }
                    return comboLineCopy;
                }),
                pricelist
            );
        });
        const combo_children_lines = this.get_orderlines().filter(
            (line) => line.price_type === "original" && line.comboParent
        );
        combo_children_lines.forEach((line) => {
            line.set_unit_price(
                attributes_prices[line.comboParent.id].find(
                    (item) => item.comboLine.id === line.comboLine.id
                ).price
            );
            self.fix_tax_included_price(line);
        });
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.new_currency = this.pos.currency;
        return json;
    },

    init_from_JSON(json){
        super.init_from_JSON(...arguments);
        var self = this
        var n_crncy = {};
        var config_currencies = [];

        for (var i = 0; i < self.pos.pricelists.length; i++) {
            if (self.pos.pricelists[i]){
                config_currencies.push(self.pos.pricelists[i].currency_id[0])
            }
        }
        for (var i = 0; i < self.pos.currencies.length; i++) {
            if (json.new_currency != undefined){
                if(self.pos.currencies[i].id == json.new_currency.id){
                    n_crncy= self.pos.currencies[i];
                    break;
                }
            }
        }
        var have = config_currencies.push(json.new_currency);
        if(have)
        {
            this.new_currency = n_crncy;
            this.pos.currency = n_crncy;
        }
        else{
            this.pricelist = this.pos.default_pricelist;
            this.new_currency = this.pos.currency;
        }   
    },
});