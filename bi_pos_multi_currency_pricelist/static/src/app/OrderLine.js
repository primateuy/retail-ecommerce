/** @odoo-module */

import { Orderline } from "@point_of_sale/app/store/models";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(Orderline.prototype, {
    getDisplayData() {
        var self = this;
        let all_curr = this.pos.currencies

        all_curr.forEach(function (curr) {
            if (self.order.pricelist){
                
                if (curr.id == self.order.pricelist.currency_id[0]){
                    self.pos.currency = curr
                }
            }
           
        });

        var currency = this.pos.currency;

        var converted_price = currency ? this.get_display_price() * currency.currency_convert : orderline.price;
        if (this.pos.mainScreen.component.name == 'TicketScreen'){

            return {
                productName: this.get_full_product_name(),
                price:
                    this.get_discount_str() === "100"
                        ? "free"
                        : this.env.utils.formatCurrency(converted_price),

                        
                qty: this.get_quantity_str(),
                unit: this.get_unit().name,
                unitPrice: this.env.utils.formatCurrency(converted_price),
                oldUnitPrice: this.env.utils.formatCurrency(this.get_old_unit_display_price()),
                discount: this.get_discount_str(),
                customerNote: this.get_customer_note(),
                internalNote: this.getNote(),
                comboParent: this.comboParent?.get_full_product_name(),
                pack_lot_lines: this.get_lot_lines(),
                price_without_discount: this.env.utils.formatCurrency(
                    this.getUnitDisplayPriceBeforeDiscount()
                ),
                attributes: this.attribute_value_ids
                    ? this.findAttribute(this.attribute_value_ids, this.custom_attribute_value_ids)
                    : [],
            };
        }else{
            return {
                productName: this.get_full_product_name(),
                price:
                    this.get_discount_str() === "100"
                        ? "free"
                        : this.env.utils.formatCurrency(this.get_display_price()),

                        
                qty: this.get_quantity_str(),
                unit: this.get_unit().name,
                unitPrice: this.env.utils.formatCurrency(this.get_unit_display_price()),
                oldUnitPrice: this.env.utils.formatCurrency(this.get_old_unit_display_price()),
                discount: this.get_discount_str(),
                customerNote: this.get_customer_note(),
                internalNote: this.getNote(),
                comboParent: this.comboParent?.get_full_product_name(),
                pack_lot_lines: this.get_lot_lines(),
                price_without_discount: this.env.utils.formatCurrency(
                    this.getUnitDisplayPriceBeforeDiscount()
                ),
                attributes: this.attribute_value_ids
                    ? this.findAttribute(this.attribute_value_ids, this.custom_attribute_value_ids)
                    : [],
            };
        }
    }
});
