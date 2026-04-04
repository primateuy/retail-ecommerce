/** @odoo-module */

import {_t} from "@web/core/l10n/translation";
import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import {ErrorPopup} from "@point_of_sale/app/errors/popups/error_popup";

/**
 * Terminal de pago Fiserv ITD: compra, polling por bus, anulación por ticket.
 * Los datos base (PosID, SystemId, Branch, etc.) se alinean con la especificación ITD v3.5.
 */
export class PaymentFiserv extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.paymentLineResolvers = {};
    }

    /**
     * ITD devuelve ResponseCode como número (p. ej. 0) o string ("0"); unifica para comparar.
     */
    static isItdResponseCodeOk(code) {
        return String(code ?? "").trim() === "0";
    }

    /**
     * Arma el bloque común de cabecera ITD para cada request.
     */
    get_base_data() {
        let branch = this.payment_method.fiserv_branch;
        if (
            (branch === undefined || branch === null || branch === "") &&
            this.payment_method.codigo_sucursal !== undefined &&
            this.payment_method.codigo_sucursal !== null
        ) {
            branch = String(this.payment_method.codigo_sucursal);
        }
        return {
            PosID: this.payment_method.codigo_terminal,
            SystemId: this.payment_method.codigo_sistema,
            Branch: branch || "",
            ClientAppId: this.payment_method.client_app_id,
            UserId: `${this.pos.user.id}`,
            TransactionDateTimeyyyyMMddHHmmssSSS: this.get_current_date(),
        };
    }

    get_current_date() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");
        const hours = String(now.getHours()).padStart(2, "0");
        const minutes = String(now.getMinutes()).padStart(2, "0");
        const seconds = String(now.getSeconds()).padStart(2, "0");
        const milliseconds = String(now.getMilliseconds()).padStart(3, "0");
        return `${year}${month}${day}${hours}${minutes}${seconds}${milliseconds}`;
    }

    pending_fiserv_line() {
        return this.pos.getPendingPaymentLine("fiserv");
    }

    handle_odoo_connection_failure(data = {}) {
        const line = this.pending_fiserv_line();
        if (line) {
            line.set_payment_status("retry");
        }
        this._show_error("No hay respuesta del servidor Odoo");
        return Promise.reject(data);
    }

    _show_error(msg, title) {
        if (!title) {
            title = _t("Fiserv ITD");
        }
        this.env.services.popup.add(ErrorPopup, {
            title: title,
            body: msg,
        });
    }

    async send_payment_request(cid) {
        await super.send_payment_request(cid);

        const order = this.pos.get_order();
        const line = order.selected_paymentline;
        const orderlines = order.get_orderlines();
        let has_refunded_line = false;
        const refunded_ids = [];

        orderlines.forEach(function (orderline) {
            if (orderline.refunded_orderline_id) {
                has_refunded_line = true;
                refunded_ids.push(orderline.refunded_orderline_id);
            }
        });

        if (line.amount <= 0 && !has_refunded_line) {
            this._show_error("El monto del pago debe ser mayor a 0.0");
            return Promise.resolve();
        }

        if (line.amount >= 0 && has_refunded_line) {
            this._show_error("El monto del pago debe ser menor a 0.0");
            return Promise.resolve();
        }

        const total_order_amount = Math.round(Math.abs(order.get_total_with_tax()) * 100);
        const total_order_amount_without_tax = Math.round(Math.abs(order.get_total_without_tax()) * 100);
        const amount_to_send_by_100 = Math.round(Math.abs(line.amount) * 100);
        const amount_to_send_float = Math.abs(line.amount);

        const currency = this.pos.currency.name;
        let currency_code = "858";
        if (currency === "USD") {
            currency_code = "840";
        }

        let numCuotas = 1;
        if (line.installments !== undefined && line.installments !== null) {
            const parsed = parseInt(line.installments, 10);
            if (!isNaN(parsed) && parsed >= 1) {
                numCuotas = parsed;
            }
        }

        let data = this.get_base_data();
        // Cuerpo alineado con ITD (ej. testitd.firstdata.com processFinancialPurchase).
        data.Amount = `${amount_to_send_by_100}`;
        data.Quotas = numCuotas;
        data.Plan = 0;
        data.Currency = currency_code;
        data.TaxRefund = 0;
        data.TaxableAmount = `${total_order_amount_without_tax}`;
        data.InvoiceAmount = `${total_order_amount}`;
        data.InvoiceNumber = "";
        data.Installments = numCuotas;
        data.TicketNumber = "";
        data.NeedToReadCard = true;

        if (has_refunded_line) {
            const odoo_backend_response = await this.env.services.orm.silent
                .call("pos.payment.method", "get_ticket_number", [
                    [this.payment_method.id],
                    refunded_ids,
                    amount_to_send_float,
                ])
                .catch(this.handle_odoo_connection_failure.bind(this));

            if (!odoo_backend_response.TicketNumber) {
                this._show_error("No se encontró número de ticket para reembolsar");
                return Promise.resolve();
            }
            data = this.get_base_data();
            data.TicketNumber = odoo_backend_response.TicketNumber;
            data.Acquirer = odoo_backend_response.Acquirer;
        }

        return this.enviar_pago(data, has_refunded_line).then((res) => {
            return this.handle_response_enviar_pago(res);
        });
    }

    async enviar_pago(data, has_refunded_line) {
        const order = this.pos.get_order();
        const pos_session_id = order.pos_session_id;

        return this.env.services.orm.silent
            .call("pos.payment.method", "enviar_pago", [[this.payment_method.id], data, pos_session_id, has_refunded_line])
            .catch(this.handle_odoo_connection_failure.bind(this));
    }

    handle_response_enviar_pago(response) {
        const line = this.pending_fiserv_line();

        if (!PaymentFiserv.isItdResponseCodeOk(response.ResponseCode)) {
            const msg_error = `Error ${response.ResponseCode}: ${response.msg || ""}`;
            this._show_error(msg_error);
            line.set_payment_status("force_done");
            return Promise.resolve();
        }
        line.set_payment_status("waitingCard");
        line.transaction_id =
            response.TransactionId !== undefined && response.TransactionId !== null
                ? String(response.TransactionId)
                : "";
        return this.waitForPaymentConfirmation();
    }

    waitForPaymentConfirmation() {
        return new Promise((resolve) => {
            this.paymentLineResolvers[this.pending_fiserv_line().cid] = resolve;
        });
    }

    send_payment_cancel(order, cid) {
        super.send_payment_cancel(order, cid);

        const line = order.selected_paymentline;
        line.cancelled = true;

        const data = this.get_base_data();
        data.TransactionId = line.transaction_id;

        return this.cancelar_pago(data).then((response) => {
            if (!PaymentFiserv.isItdResponseCodeOk(response.ResponseCode)) {
                this._show_error("Falló la cancelación del pago");
                line.cancelled = false;
                return false;
            }
            line.cancelled = true;
            const resolver = this.paymentLineResolvers?.[line.cid];
            if (resolver) {
                resolver(false);
            } else {
                line.handle_payment_response(false);
            }
            return true;
        });
    }

    cancelar_pago(data) {
        return this.env.services.orm.silent
            .call("pos.payment.method", "cancelFinancialPurchase", [[this.payment_method.id], data])
            .catch(this.handle_odoo_connection_failure.bind(this));
    }

    /**
     * Procesa el payload enviado por el bus tras el polling backend (ITD Query).
     */
    async handleFiservStatusResponse(payload) {
        const line = this.pending_fiserv_line();
        if (line.cancelled) {
            return;
        }

        const approvedPosCodes = ["0", "00", "08", "10", "11", "85", "OF", "Y1", "Y3"];
        const response_code = String(payload.ResponseCode ?? "").trim();
        const posRaw = payload.PosResponseCode ?? payload.posResponseCode;
        const pos_response_code =
            posRaw !== undefined && posRaw !== null && posRaw !== ""
                ? String(posRaw).trim().toUpperCase()
                : null;
        let isPaymentSuccessful = false;

        // Respuesta mínima ITD: solo ResponseCode 0 y TransactionId (sin PosResponseCode aún).
        if (PaymentFiserv.isItdResponseCodeOk(response_code)) {
            if (!pos_response_code) {
                isPaymentSuccessful = true;
            } else if (approvedPosCodes.includes(pos_response_code)) {
                isPaymentSuccessful = true;
            }
        }

        if (isPaymentSuccessful) {
            line.transaction_id = payload.origin_transaction_id;
            line.card_type = payload.Acquirer;
            line.ticket = payload.Ticket;
            line.cardholder_name = payload.CardOwnerName;
        } else {
            let msg_error = "";
            if (payload.timeout_error || response_code === "11") {
                msg_error = payload.msg || "Tiempo de transacción excedido. Se procesó la reversión del pago.";
                if (payload.reverse_processed) {
                    if (payload.reverse_success) {
                        msg_error += " La reversión fue exitosa. Puede intentar el pago nuevamente.";
                    } else {
                        msg_error += " Hubo un problema con la reversión. Contacte al administrador.";
                    }
                }
            } else if (payload.msg) {
                msg_error = payload.msg;
                if (pos_response_code) {
                    msg_error += ` (Código POS: ${pos_response_code})`;
                }
            } else if (pos_response_code) {
                msg_error = `Error POS RESPONSE CODE: ${pos_response_code}`;
            } else {
                msg_error = `Error en el pago. ResponseCode: ${response_code}`;
            }
            this._show_error(msg_error);
        }

        const resolver = this.paymentLineResolvers?.[line.cid];
        if (resolver) {
            resolver(isPaymentSuccessful);
        } else {
            line.handle_payment_response(isPaymentSuccessful);
        }
    }
}
