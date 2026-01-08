/** @odoo-module */

import { Order, Orderline, Payment } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(Payment.prototype, {
    setup(_defaultObj, options) {
        super.setup(...arguments);
        this.allow_check_info = this.allow_check_info || false;
        this.check_number = this.check_number || false;
        this.bank_account = this.bank_account || false;
        this.owner_name = this.owner_name || false;
        this.bank_name = this.bank_name || false;
   },
    getCheckInfo(){
        const check_info = this;
        return check_info
    },
    set_allow_check_info(allow_check_info){
        this.allow_check_info = allow_check_info;
    },
     get_allow_check_info(){
        return this.allow_check_info;
    },
    set_check_number(check_number){
      this.check_number = check_number;
    },
    get_check_number(){
        return this.check_number;
    },
    set_bank_name(bank_name){
      this.bank_name = bank_name;
    },
    get_bank_name(){
        return this.bank_name;
    },
    set_owner_name(owner_name){
      this.owner_name = owner_name;
    },
    get_owner_name(){
        return this.owner_name;
    },
    set_bank_account(bank_account){
      this.bank_account = bank_account;
    },
    get_bank_account(){
        return this.bank_account;
    },
    init_from_JSON(json){
        super.init_from_JSON(...arguments);
        this.allow_check_info = json.allow_check_info || false;
        this.check_number = json.check_number || false;
        this.bank_account = json.bank_account || false;
        this.owner_name = json.owner_name || false;
        this.bank_name = json.bank_name || false;
    },
    export_as_JSON(){
        const json = super.export_as_JSON(...arguments);
        json.allow_check_info = this.allow_check_info || false;
        json.check_number = this.check_number || false;
        json.bank_account = this.bank_account || false;
        json.owner_name = this.owner_name || false;
        json.bank_name = this.bank_name || false;
        return json;
    },
    export_for_printing() {
        const json = super.export_for_printing(...arguments);
        json.allow_check_info = this.get_allow_check_info();
        json.check_number = this.get_check_number();
        json.bank_account = this.get_bank_account();
        json.owner_name = this.get_owner_name();
        json.bank_name = this.get_bank_name();
        return json;
    }
});
