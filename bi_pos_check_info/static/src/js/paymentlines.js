
/** @odoo-module */

import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
import { patch } from "@web/core/utils/patch";
import { CheckInfoPopup } from "@bi_pos_check_info/js/check_info_popup";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";

patch(PaymentScreenPaymentLines.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        this.popup = useService("popup");
    },
    async _CheckInfoClicked(cid){
        var order = this.pos.get_order();
        let selected_paymentline = order.selected_paymentline;
        if (selected_paymentline) {
            const check_info = selected_paymentline.getCheckInfo();
            const { confirmed, payload } = await this.popup.add(CheckInfoPopup, {
                 title: 'Check',
                 array: check_info,
            });
            if (confirmed){
                var bank_name = parseInt($("#bank_id").val());
                var check_number = document.getElementById("check_number").value;
                var owner_name = document.getElementById("owner_name").value;
                var bank_account = document.getElementById("bank_account").value;
                var allow_check_info = selected_paymentline.payment_method.allow_check_info
                selected_paymentline.set_allow_check_info(allow_check_info);
                selected_paymentline.set_check_number(check_number);
                selected_paymentline.set_owner_name(owner_name);
                selected_paymentline.set_bank_account(bank_account);
                selected_paymentline.set_bank_name(bank_name);
            }
        }
    }
});