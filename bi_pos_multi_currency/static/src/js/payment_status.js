/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PaymentScreenStatus } from "@point_of_sale/app/screens/payment_screen/payment_status/payment_status";

import { Component, useEffect, useRef, useState } from "@odoo/owl";

patch(PaymentScreenStatus.prototype, {
    setup() {
        super.setup();
    },

    get changeText() {
        if(this.props.order.new_currency){
            if(this.props.order.currency_amount_pay > 0 && this.props.order.cur_pay_id != this.props.order.new_currency.id){
                return this.props.order.get_change();
            }
            else{
                return this.env.utils.formatCurrency(this.props.order.get_change());
            }
        }else{
            return this.env.utils.formatCurrency(this.props.order.get_change());    
        }
    },

    get totalDueText() {
        if(this.props.order.new_currency){            
            if(this.props.order.currency_amount_pay > 0 && this.props.order.cur_pay_id != this.props.order.new_currency.id){
                if(this.props.order.get_paymentlines().length == 0){ 
                    return this.env.utils.formatCurrency(
                        this.props.order.get_total_with_tax() + this.props.order.get_rounding_applied()
                    );
                }else{
                    return this.props.order.currency_amount_pay + this.props.order.get_rounding_applied()
                }
            }else{
                return this.env.utils.formatCurrency(
                    this.props.order.get_total_with_tax() + this.props.order.get_rounding_applied()
                );
            }
        }else{
            return this.env.utils.formatCurrency(
                this.props.order.get_total_with_tax() + this.props.order.get_rounding_applied()
            );
        }
    },
    
    get remainingText() {
        if(this.props.order.new_currency){    
            if(this.props.order.currency_amount_pay > 0 && this.props.order.cur_pay_id != this.props.order.new_currency.id){
                return this.props.order.get_due() > 0 ? this.props.order.get_due() : 0
            }else{
                return this.env.utils.formatCurrency(
                    this.props.order.get_due() > 0 ? this.props.order.get_due() : 0
                );
            }
        }else{
            return this.env.utils.formatCurrency(
                this.props.order.get_due() > 0 ? this.props.order.get_due() : 0
            );    
        }
    },

});