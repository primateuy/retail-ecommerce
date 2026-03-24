/** @odoo-module */

/**
 * Líneas de pago del POS: popup de transacción manual FORUM.
 *
 * Abre un popup dedicado (no el de cheques) con campos definidos en el
 * proveedor manual y guarda los valores en la línea de pago.
 */

import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
import { patch } from "@web/core/utils/patch";
import { ManualPaymentPopup } from "../js/manual_payment_popup";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreenPaymentLines.prototype, {
    /**
     * Servicios POS y popup para captura manual.
     */
    setup() {
        super.setup();
        this.pos = usePos();
        this.popup = useService("popup");
    },

    /**
     * Abre el popup de datos manuales y devuelve confirmación y payload.
     */
    async _openManualTransactionPopup(paymentMethod, paymentLine) {
        const order = this.pos.get_order();
        const partner = order && order.get_partner ? order.get_partner() : null;
        const partnerName = partner ? partner.name : "";
        const fieldConfigJson =
            paymentMethod.manual_payment_popup_config || "[]";
        console.debug(
            "[FORUM manual POS] Abriendo popup método=%s",
            paymentMethod.name
        );
        const { confirmed, payload } = await this.popup.add(ManualPaymentPopup, {
            title: _t("Datos de transacción manual"),
            fieldConfigJson,
            partnerName,
        });
        if (confirmed && payload && payload.values && paymentLine.set_manual_payment_values) {
            paymentLine.set_manual_payment_values(payload.values);
            console.debug(
                "[FORUM manual POS] Popup confirmado; claves capturadas: %s",
                Object.keys(payload.values).join(", ")
            );
        } else if (!confirmed) {
            console.debug("[FORUM manual POS] Popup cancelado por el usuario.");
        }
        return { confirmed, payload };
    },

    /**
     * Al agregar línea de pago manual, abre el popup automáticamente.
     */
    async addNewPaymentLine(paymentMethod) {
        await super.addNewPaymentLine(paymentMethod);
        try {
            const order = this.pos.get_order();
            if (!order || !paymentMethod.manual_transaction_enabled) {
                return;
            }
            const selectedLine = order.selected_paymentline;
            if (!selectedLine) {
                return;
            }
            const { confirmed } = await this._openManualTransactionPopup(
                paymentMethod,
                selectedLine
            );
            if (!confirmed) {
                console.debug(
                    "[FORUM manual POS] Línea de pago manual eliminada (popup cancelado)."
                );
                order.remove_paymentline(selectedLine);
            }
        } catch (error) {
            console.error("[FORUM manual POS] Error en popup:", error);
        }
    },

    /**
     * Abre el popup al pulsar el icono en la línea (comportamiento tipo cheque).
     */
    async _ManualInfoClicked(cid) {
        const order = this.pos.get_order();
        if (!order) {
            return;
        }
        const paymentLine =
            order.paymentlines.find((line) => line.cid === cid) ||
            order.selected_paymentline;
        if (!paymentLine || !paymentLine.payment_method.manual_transaction_enabled) {
            return;
        }
        await this._openManualTransactionPopup(
            paymentLine.payment_method,
            paymentLine
        );
    },
});
