/** @odoo-module */
/*
 * Interfaz de pago Getnet/TransAct para el TPV.
 * El posteo y el polling viven en el server; acá solo se dispara el RPC
 * y se retiene una promesa por línea que resuelve el bus
 * (GETNET_LATEST_RESPONSE, ver pos_bus.js).
 */
import {_t} from "@web/core/l10n/translation";
import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import {ErrorPopup} from "@point_of_sale/app/errors/popups/error_popup";

export class PaymentGetnet extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.paymentLineResolvers = {};
    }

    async send_payment_request(cid) {
        await super.send_payment_request(...arguments);
        const order = this.pos.get_order();
        const line = order.get_paymentline(cid);
        const isRefund = line.amount < 0;
        const refundedOrderIds = [
            ...new Set(
                order
                    .get_orderlines()
                    .map((l) => l.refunded_orderline_id?.order?.backendId)
                    .filter(Boolean)
            ),
        ];
        const data = {
            amount: line.amount,
            currency_id: this.pos.currency.id,
            session_id: this.pos.pos_session.id,
            config_id: this.pos.config.id,
            tracking_number: order.trackingNumber || "",
            order_uid: order.uid,
            is_refund: isRefund,
            refunded_order_ids: refundedOrderIds,
        };
        try {
            const resp = await this.pos.orm.silent.call(
                "pos.payment.method",
                "getnet_enviar_pago",
                [[this.payment_method.id], data]
            );
            if (resp.rc !== 0) {
                this._getnet_show_error(resp.msg || _t("Posteo rechazado por TransAct."));
                return false;
            }
            line.getnet_token = resp.token;
            line.transaction_id = resp.tx_reference;
            line.set_payment_status("waitingCard");
            return await this.waitForPaymentConfirmation(line);
        } catch (error) {
            this._getnet_show_error(_t("No se pudo contactar al servidor Getnet."));
            console.error("Getnet:", error);
            return false;
        }
    }

    waitForPaymentConfirmation(line) {
        return new Promise((resolve) => {
            this.paymentLineResolvers[line.cid] = resolve;
        });
    }

    async send_payment_cancel(order, cid) {
        await super.send_payment_cancel(...arguments);
        const line = order.get_paymentline(cid);
        if (!line || !line.getnet_token) {
            return true;
        }
        const resp = await this.pos.orm.silent.call(
            "pos.payment.method",
            "getnet_cancelar",
            [[this.payment_method.id], line.getnet_token]
        );
        if (resp.rc !== 0) {
            this._getnet_show_error(
                resp.msg || _t("No se pudo cancelar (puede estar ya aprobada).")
            );
            return false;
        }
        const resolver = this.paymentLineResolvers[line.cid];
        if (resolver) {
            resolver(false);
            delete this.paymentLineResolvers[line.cid];
        }
        return true;
    }

    /**
     * Llamado por pos_bus.js al llegar GETNET_LATEST_RESPONSE.
     */
    handleGetnetStatusResponse(payload) {
        const line = this.pos.getPendingPaymentLine("getnet");
        if (!line) {
            return;
        }
        if (payload.approved) {
            line.card_type = payload.card_type;
            line.ticket = payload.ticket;
            line.transaction_id = payload.tx_reference;
        } else {
            this._getnet_show_error(
                payload.msg || _t("La transacción no fue aprobada.")
            );
        }
        const resolver = this.paymentLineResolvers[line.cid];
        if (resolver) {
            resolver(payload.approved);
            delete this.paymentLineResolvers[line.cid];
        } else {
            line.handle_payment_response(payload.approved);
        }
    }

    _getnet_show_error(msg) {
        this.env.services.popup.add(ErrorPopup, {
            title: _t("Terminal Getnet"),
            body: msg,
        });
    }
}
