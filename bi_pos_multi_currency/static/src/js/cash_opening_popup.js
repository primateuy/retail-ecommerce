/** @odoo-module */

import { CashOpeningPopup } from "@point_of_sale/app/store/cash_opening_popup/cash_opening_popup";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { Component, onMounted, useRef } from "@odoo/owl";

patch(CashOpeningPopup.prototype, {

    setup() {
        super.setup();

        var pay_journal_currency = [];

        for (let payment of this.pos.config.payment_method_ids) {
            var payment_methods = this.pos.payment_methods_by_id[payment]
            if(payment_methods.currency_id){
                if(payment_methods.currency_id[0] != this.pos.company.currency_id[0]){
                    pay_journal_currency.push(payment_methods)
                }               
            }
        }

        this.state_data = useState({
            payment_currency: pay_journal_currency ,
            openingPaymentCash: this.pos.pos_session.bi_start_balance || 0,
        })
    },

    async confirm() {
        this.orm.call("pos.session", "set_cashbox_pos", [
            this.pos.pos_session.id,
            parseFloat(this.state.openingCash),
            this.state.notes,
        ]);

        super.confirm();

        if (this.state_data.payment_currency.length > 0){
            this.orm.call("pos.session", "get_open_new_balance", [,
                parseFloat(this.state_data.openingPaymentCash),
                this.pos.pos_session.id,
                this.state_data.payment_currency[0].journal_id[0],
                this.state_data.payment_currency[0].currency_id[0],
            ]);            
        }
    }
})