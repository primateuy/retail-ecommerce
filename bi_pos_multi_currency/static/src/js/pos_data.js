/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { Order, Payment } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
	// @Override
	async _processData(loadedData) {
		await super._processData(...arguments);
		this.poscurrency = await this.loadedDataCurrency();
		this.journals = loadedData['account.journal'];
	},

	async loadedDataCurrency(){
		let domain = [['id', 'in', this.config.selected_currency]];
		var	fields = ['name','symbol','position','rounding','rate','rate_in_company_currency','inverse_rate']
		var cur = await this.orm.call("res.currency", "search_read", [
            domain,fields
        ]);
        return cur;
	}
});

patch(Order.prototype, {
	setup() {
		super.setup(...arguments);
		this.currency_amount = this.currency_amount || "";
		this.currency_symbol = this.currency_symbol || "";
		this.currency_name = this.currency_name || "";
		this.currency_amount_pay = this.currency_amount_pay || "";
		this.currency_symbol_pay = this.currency_symbol_pay || "";
		this.currency_name_pay = this.currency_name_pay || "";
		this.cur_pay_id = this.cur_pay_id || "";
		
	},

	add_paymentline(payment_method) {
		this.assert_editable();
		if (this.electronic_payment_in_progress()) {
			return false;
		} else {
			var newPaymentline = new Payment(
				{ env: this.env },
				{ order: this, payment_method: payment_method, pos: this.pos }
			);
			
			this.paymentlines.add(newPaymentline);
			this.select_paymentline(newPaymentline);

			let currency = this.pos.poscurrency;
			if(this.selected_paymentline.payment_method){
				for (let j of this.pos.journals) {
					if(j['id'] == this.selected_paymentline.payment_method.journal_id[0]){
						if(j.currency_id != false && j.currency_id[0] != this.pos.currency.id){
							for(var i=0;i<currency.length;i++){
								if(j.currency_id[0] == currency[i].id){
									let c_rate = this.pos.currency.rate/currency[i].rate;
									let currency_in_pos = (currency[i].rate/this.pos.currency.rate).toFixed(6);
									let curr_tot =this.get_due()*currency_in_pos;
									if(curr_tot){										
										this.selected_paymentline.set_cur_pay_id(currency[i].id);
										this.selected_paymentline.set_curname_pay(currency[i].name);
										this.selected_paymentline.set_currency_symbol_pay(currency[i].symbol);
										this.selected_paymentline.set_curamount_pay(parseFloat(curr_tot.toFixed(2)));
										this.set_curamount_pay(parseFloat(curr_tot.toFixed(2)));
										this.set_symbol_pay(currency[i].symbol);
										this.set_curname_pay(currency[i].name);	
										this.set_cur_pay_id(currency[i].id);										
									}									
								}
							}
						}else{
							this.set_cur_pay_id(j.currency_id[0]);
						}
					}
				}				
			}

			if (this.pos.config.cash_rounding) {
				this.selected_paymentline.set_amount(0);
			}
			newPaymentline.set_amount(this.get_due());

			if (payment_method.payment_terminal) {
				newPaymentline.set_payment_status("pending");
			}
			return newPaymentline;
		}
	}, 

	set_symbol(currency_symbol){
		this.currency_symbol = currency_symbol;
	},

	get_symbol(currency_symbol){
		return this.currency_symbol;
	},

	set_curamount(currency_amount){
		this.currency_amount = currency_amount;
	},

	get_curamount(currency_amount){
		return this.currency_amount;
	},

	set_curname(currency_name){
		this.currency_name = currency_name;
	},

	get_curname(currency_name){
		return this.currency_name;
	},

	set_symbol_pay(currency_symbol_pay){
		this.currency_symbol_pay = currency_symbol_pay;
	},

	get_symbol_pay(currency_symbol_pay){
		return this.currency_symbol_pay;
	},

	set_curamount_pay(currency_amount_pay){
		this.currency_amount_pay = currency_amount_pay;
	},

	get_curamount_pay(currency_amount_pay){
		return this.currency_amount_pay;
	},

	set_cur_pay_id(cur_pay_id){
		this.cur_pay_id = cur_pay_id;
	},

	get_cur_pay_id(cur_pay_id){
		return this.cur_pay_id;
	},
	
	set_curname_pay(currency_name_pay){
		this.currency_name_pay = currency_name_pay;
	},

	get_curname_pay(currency_name_pay){
		return this.currency_name_pay;
	},

	init_from_JSON(json){
		super.init_from_JSON(...arguments);
		this.currency_amount = json.currency_amount || "";
		this.currency_symbol = json.currency_symbol || "";
		this.currency_name = json.currency_name || "";
		this.currency_amount_pay = json.currency_amount_pay || "";
		this.currency_symbol_pay = json.currency_symbol_pay || "";
		this.currency_name_pay = json.currency_name_pay || "";
		this.cur_pay_id = json.cur_pay_id || "";
	},

	export_as_JSON(){
		const json = super.export_as_JSON(...arguments);
		json.currency_amount = this.get_curamount() || 0.0;
		json.currency_symbol = this.get_symbol() || false;
		json.currency_name = this.get_curname() || false;
		json.currency_amount_pay = this.get_curamount_pay() || 0.0;
		json.currency_symbol_pay = this.get_symbol_pay() || false;
		json.currency_name_pay = this.get_curname_pay() || false;
		json.cur_pay_id = this.get_cur_pay_id() || false;
		return json;
	},

	export_for_printing() {
		const json = super.export_for_printing(...arguments);
		json.currency_amount = this.get_curamount() || 0.0;
		json.currency_symbol = this.get_symbol() || false;
		json.currency_name = this.get_curname() || false;
		json.currency_amount_pay = this.get_curamount_pay() || 0.0;
		json.currency_symbol_pay = this.get_symbol_pay() || false;
		json.currency_name_pay = this.get_curname_pay() || false;
		json.cur_pay_id = this.get_cur_pay_id() || false;
		return json;
	},
});


patch(Payment.prototype, {
	setup() {
		super.setup(...arguments);
		this.currency_amount = this.currency_amount || 0.0;
		this.currency_name = this.currency_name || this.pos.currency.name;
		this.currency_symbol = this.currency_symbol || this.pos.currency.symbol;
		this.currency_amount_pay = this.currency_amount_pay || 0.0;
		this.currency_name_pay = this.currency_name_pay || "";
		this.currency_symbol_pay = this.currency_symbol_pay || "";
		this.cur_pay_id = this.cur_pay_id || "";
	},
	set_curname(currency_name){
		this.currency_name = currency_name;
	},

	set_curamount(currency_amount){
		this.currency_amount = currency_amount;
	},

	set_currency_symbol(currency_symbol){
		this.currency_symbol = currency_symbol;
	},

	set_curname_pay(currency_name_pay){
		this.currency_name_pay = currency_name_pay;
	},

	set_curamount_pay(currency_amount_pay){
		this.currency_amount_pay = currency_amount_pay;
	},

	set_currency_symbol_pay(currency_symbol_pay){
		this.currency_symbol_pay = currency_symbol_pay;
	},

	set_cur_pay_id(cur_pay_id){
		this.cur_pay_id = cur_pay_id;
	},
	
	init_from_JSON(json){
		super.init_from_JSON(...arguments);
		this.currency_amount = json.currency_amount || 0.0;
		this.currency_name = json.currency_name || this.pos.currency.name;
		this.currency_symbol = json.currency_symbol || this.pos.currency.symbol;
		this.currency_amount_pay = json.currency_amount_pay || 0.0;
		this.currency_name_pay = json.currency_name_pay || this.pos.currency.name;
		this.currency_symbol_pay = json.currency_symbol_pay || this.pos.currency.symbol;
		this.cur_pay_id = json.cur_pay_id || this.pos.currency.id;
	},

	export_as_JSON(){
		const json = super.export_as_JSON(...arguments);
		json.currency_amount = this.currency_amount || 0.0;
		json.currency_name = this.currency_name || this.pos.currency.name;
		json.currency_symbol = this.currency_symbol || this.pos.currency.symbol;
		json.currency_amount_pay = this.currency_amount_pay || 0.0;
		json.currency_name_pay = this.currency_name_pay || this.pos.currency.name;
		json.currency_symbol_pay = this.currency_symbol_pay || this.pos.currency.symbol;
		json.cur_pay_id = this.cur_pay_id || this.pos.currency.id;

		return json;
	},

	export_for_printing() {
		const json = super.export_for_printing(...arguments);
		json.currency_amount = this.currency_amount || 0.0;
		json.currency_name = this.currency_name || this.pos.currency.name;
		json.currency_symbol = this.currency_symbol || this.pos.currency.symbol;
		json.currency_amount_pay = this.currency_amount_pay || 0.0;
		json.currency_name_pay = this.currency_name_pay || this.pos.currency.name;
		json.currency_symbol_pay = this.currency_symbol_pay || this.pos.currency.symbol;
		json.cur_pay_id = this.cur_pay_id || this.pos.currency.id;
		return json;
	},
});
