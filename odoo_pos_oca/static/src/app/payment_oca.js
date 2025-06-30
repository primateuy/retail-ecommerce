/** @odoo-module */

import {_t} from "@web/core/l10n/translation";
import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import {ErrorPopup} from "@point_of_sale/app/errors/popups/error_popup";
import {sprintf} from "@web/core/utils/strings";

const {DateTime} = luxon;

export class PaymentOCA extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.paymentLineResolvers = {};
    }

    // ******************************************
    // HELPERS
    // ******************************************

    get_base_data() {
        var codigo_sucursal = `${this.payment_method.codigo_sucursal}`;
        var user_id = `${this.pos.user.id}`;

        return {
            "PosID": this.payment_method.codigo_terminal,
            "SystemId": this.payment_method.codigo_sistema,
            "Branch": codigo_sucursal,
            "ClientAppId": this.payment_method.client_app_id,
            "UserId": user_id,
            "TransactionDateTimeyyyyMMddHHmmssSSS": this.get_current_date(),
        }
    }

    get_current_date() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        const milliseconds = String(now.getMilliseconds()).padStart(3, '0');
        return `${year}${month}${day}${hours}${minutes}${seconds}${milliseconds}`;
    }

    pending_oca_line() {
        return this.pos.getPendingPaymentLine("oca");
    }

    handle_odoo_connection_failure(data = {}) {
        // handle timeout
        var line = this.pending_oca_line();
        if (line) {
            line.set_payment_status("retry");
        }
        this._show_error("No hay respuesta del servidor Odoo");

        return Promise.reject(data); // prevent subsequent onFullFilled's from being called
    }

    _show_error(msg, title) {
        if (!title) {
            title = _t("OCA Error");
        }
        this.env.services.popup.add(ErrorPopup, {
            title: title,
            body: msg,
        });
    }

    // ******************************************
    // SEND
    // ******************************************

    async send_payment_request(cid) {
        console.log('-----------------PaymentOCA send_payment_request------------------');
        await super.send_payment_request(cid);

        var order = this.pos.get_order();
        var line = order.selected_paymentline;
        var orderlines = order.get_orderlines(); // this returns a plain array
        var has_refunded_line = false;
        var refunded_ids = [];

        orderlines.forEach(function (orderline) {
            if (orderline.refunded_orderline_id) {
                has_refunded_line = true;
                refunded_ids.push(orderline.refunded_orderline_id);
            }
        });

        if (line.amount <= 0 && !has_refunded_line) {
            this._show_error('El monto del pago debe ser mayor a 0.0');
            return Promise.resolve();
        }

        if (line.amount >= 0 && has_refunded_line) {
            this._show_error('El monto del pago debe ser menor a 0.0');
            return Promise.resolve();
        }

        var total_order_amount = Math.round(Math.abs(order.get_total_with_tax()) * 100)
        var total_order_amount_without_tax = Math.round(Math.abs(order.get_total_without_tax()) * 100);
        var amount_to_send_by_100 = Math.round(Math.abs(line.amount) * 100);
        var amount_to_send_float = Math.abs(line.amount);

        var currency = this.pos.currency.name;

        var currency_code = "858";

        if (currency === "USD") {
            currency_code = "840";
        }

        var data = this.get_base_data();
        data.Amount = `${amount_to_send_by_100}`;
        data.Quotas = "0";
        data.Plan = "0";
        data.Currency = currency_code;
        //data.TaxRefund = "0";
        data.TaxRefund = "99";
        data.TaxableAmount = `${total_order_amount_without_tax}`;
        data.InvoiceAmount = `${total_order_amount}`;
        // Enviar un InvoiceNumber simple - el backend se encargará de encontrar la orden correcta
        data.InvoiceNumber = "1";
        // Agregar campos que pueden ser obligatorios
        data.Installments = "1";
        data.TicketNumber = "";

        // Log para debuggear los datos que se envían
        console.log('OCA Payment Data being sent:', JSON.stringify(data, null, 2));
        console.log('InvoiceNumber sent:', data.InvoiceNumber);

        if (has_refunded_line) {
            var odoo_backend_response = await this.env.services.orm.silent.call(
                "pos.payment.method",
                "get_ticket_number",
                [[this.payment_method.id], refunded_ids, amount_to_send_float]
            ).catch(this.handle_odoo_connection_failure.bind(this));

            if (!odoo_backend_response.TicketNumber) {
                this._show_error('No se encontró número de ticket para reembolsar');
                return Promise.resolve();
            }
            data = this.get_base_data();
            data.TicketNumber = odoo_backend_response.TicketNumber;
            data.Acquirer = odoo_backend_response.Acquirer;
        }

        return this.enviar_pago(data, has_refunded_line).then((data) => {
            return this.handle_response_enviar_pago(data);
        });
    }

    async enviar_pago(data, has_refunded_line) {
        var self = this;
        var order = self.pos.get_order();
        var pos_session_id = order.pos_session_id;

        return this.env.services.orm.silent.call(
            "pos.payment.method",
            "enviar_pago",
            [[this.payment_method.id], data, pos_session_id, has_refunded_line]
        ).catch(this.handle_odoo_connection_failure.bind(this));
    }

    handle_response_enviar_pago(response) {
        var line = this.pending_oca_line();

        if (response.ResponseCode !== '0') {
            console.log('handle_response_enviar_pago', 'ERROR')
            var msg_error = `Error ${response.ResponseCode}: ${response.msg}`
            this._show_error(msg_error);
            line.set_payment_status('force_done');
            return Promise.resolve();
        } else {
            console.log('handle_response_enviar_pago', 'OK')
            line.set_payment_status('waitingCard');
            line.transaction_id = response.TransactionId;
            return this.waitForPaymentConfirmation();
        }
    }

    waitForPaymentConfirmation() {
        return new Promise((resolve) => {
            this.paymentLineResolvers[this.pending_oca_line().cid] = resolve;
        });
    }

    // ******************************************
    // CANCEL
    // ******************************************

    send_payment_cancel(order, cid) {
        super.send_payment_cancel(order, cid);

        var line = order.selected_paymentline;
        line.cancelled = true;

        var data = this.get_base_data();
        data.TransactionId = line.transaction_id;

        return this.cancelar_pago(data).then((response) => {
            // Only valid response is a 200 OK HTTP response which is
            // represented by true.
            if (response.ResponseCode !== '0') {
                this._show_error("Falló la cancelación del pago");
                line.cancelled = false;
                return false;
            } else {
                line.cancelled = true;
                const resolver = this.paymentLineResolvers?.[line.cid];
                if (resolver) {
                    resolver(false);
                } else {
                    line.handle_payment_response(false);
                }
                return true;
            }
        });
    }

    cancelar_pago(data) {
        return this.env.services.orm.silent.call(
            "pos.payment.method",
            "cancelFinancialPurchase",
            [[this.payment_method.id], data]
        ).catch(this.handle_odoo_connection_failure.bind(this));
    }

    // ******************************************
    // BUS RESPONSE
    // ******************************************

    async handleOCAStatusResponse(payload) {
        console.log("handleOCAStatusResponse");
        const line = this.pending_oca_line();
        if (line.cancelled) {
            return;
        }

        // var data = this.get_base_data();
        // data.TransactionId = TransactionId;
        // const notification = await this.env.services.orm.silent.call(
        //     "pos.payment.method",
        //     "consultar_estado_final",
        //     [[this.payment_method.id], data]
        // );
        // if (!notification) {
        //     this.handle_odoo_connection_failure();
        //     return;
        // }

        var array_of_correct_codes = ['00', '08', '10', '11', '85'];
        var response_code = payload.ResponseCode;
        var pos_response_code = payload.PosResponseCode;
        var isPaymentSuccessful = false;

        if (response_code === '0') {
            if (pos_response_code && array_of_correct_codes.includes(pos_response_code)) {
                isPaymentSuccessful = true;
            }
        }

        if (isPaymentSuccessful) {
            line.transaction_id = payload.origin_transaction_id;
            line.card_type = payload.Acquirer;
            line.ticket = payload.Ticket;
            line.cardholder_name = payload.CardOwnerName;
        } else {
            var msg_error = `Error POS RESPONSE CODE: ${pos_response_code}`;
            this._show_error(msg_error);
        }

        // when starting to wait for the payment response we create a promise
        // that will be resolved when the payment response is received.
        // In case this resolver is lost ( for example on a refresh ) we
        // we use the handle_payment_response method on the payment line
        const resolver = this.paymentLineResolvers?.[line.cid];
        if (resolver) {
            resolver(isPaymentSuccessful);
        } else {
            line.handle_payment_response(isPaymentSuccessful);
        }
    }
}
