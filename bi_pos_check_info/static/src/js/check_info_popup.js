//** @odoo-module */

import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { onMounted, useRef, useState } from "@odoo/owl";
//import { ConfirmPopup } from "@point_of_sale/app/utils/confirm_popup/confirm_popup";

export class CheckInfoPopup extends AbstractAwaitablePopup {
    static template = "bi_pos_check_info.CheckInfoPopup";
    static defaultProps = {
        confirmText: _t("Apply"),
        title: _t(""),
        body: '',
        cancelText: _t("Cancel"),
    };
    setup() {
        super.setup();
        this.pos = usePos();
        this.popup = useService("popup");
        this.state = useState({ array: this._initialize(this.props.array) });
    }
    _initialize(array) {
            if (array.length === 0) return [this._emptyItem()];
            return array
        }

    mounted() {
        $('#del_date').datetimepicker({
            format: 'YYYY-MM-DD HH:mm:ss',
            inline: true,
            sideBySide: true
        });
    }

    async select() {
        this.props.close({ confirmed: true, payload: null });
    }
    confirm() {
        var owner_name = document.getElementById("owner_name").value;
        var check_number = document.getElementById("check_number").value;
        var bank_account = document.getElementById("bank_account").value;
        if (!owner_name || !check_number || !bank_account) {
            alert("Please Fill Check Details !!")
        }else{
            return super.confirm();
        }
    }

    cancel() {
        this.props.close({ confirmed: false, payload: null });
    }

    getPayload() {
        return {
            newArray: this.state.array
//                    .filter((item) => item.text.trim() !== '')
//                    .map((item) => Object.assign({}, item)),
        };
    }
}
