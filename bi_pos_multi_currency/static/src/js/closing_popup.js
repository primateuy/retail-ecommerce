/** @odoo-module */

import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";

patch(ClosePosPopup, {
    props: [
    ...ClosePosPopup.props,
        "pay_amount",
    ],

});

patch(ClosePosPopup.prototype, {
    setup() {
        super.setup();
    },

    getInitialState() {
        const initialState = { notes: "", payments: {} };
        if (this.pos.config.cash_control) {
            initialState.payments[this.props.default_cash_details.id] = {
                counted: "0",
            };
        }
        this.props.other_payment_methods.forEach((pm) => {
            if (pm.type === "bank") {
                initialState.payments[pm.id] = {
                    counted: this.env.utils.formatCurrency(pm.amount, false),
                };
            }
        });
        this.props.pay_amount.forEach((pm) => {
            if (pm.type === "cash") {
                initialState.payments[pm.id] = {
                    counted: "0",
                };
            }
        });
        return initialState;
    },

    setManualCashInputCustom(amount) {
        this.orm.call("pos.session", "update_closing_balance", [,
            this.pos.pos_session.id,
            amount,
        ]);
    },

    getMaxDifference() {
        return Math.max(
            ...Object.keys(this.state.payments).map((id) =>
                this.getDifferenceCash(parseInt(id))
            )
        );
    },


    getDifferenceCash(paymentId) {

        const counted = this.state.payments[paymentId].counted;
        if (!this.env.utils.isValidFloat(counted)) {
            return NaN;
        }
        const expectedAmount =
            paymentId === this.props.default_cash_details?.id
                ? this.props.pay_amount
                : this.props.pay_amount.find((pm) => pm.id === paymentId).amount;

        var amount_check = parseFloat(counted) - expectedAmount;
        if(isNaN(amount_check)){
            return 0;
        }else{
            return parseFloat(counted) - expectedAmount;
        }
    }
});
