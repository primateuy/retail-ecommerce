/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";

/**
 * Cuando el método de pago tiene "No superar saldo de Orden" (limit_closing_cash_to_balance),
 * el monto ingresado no puede superar el saldo pendiente de la orden.
 * Se aplica al momento de agregar/editar el pago en la pantalla de pago, no solo en cierre.
 */
patch(PaymentScreen.prototype, {
    updateSelectedPaymentline(amount = false) {
        if (!this.selectedPaymentLine) {
            return super.updateSelectedPaymentline(...arguments);
        }

        // Resolver el monto igual que el padre (buffer o argumento)
        let resolvedAmount = amount;
        if (resolvedAmount === false) {
            if (this.numberBuffer.get() === null) resolvedAmount = null;
            else if (this.numberBuffer.get() === "") resolvedAmount = 0;
            else resolvedAmount = this.numberBuffer.getFloat();
        }

        const method = this.selectedPaymentLine.payment_method;
        if (
            method?.limit_closing_cash_to_balance &&
            resolvedAmount !== null &&
            typeof resolvedAmount === "number"
        ) {
            const maxAllowed = this.currentOrder.get_due(this.selectedPaymentLine);
            if (resolvedAmount > maxAllowed) {
                resolvedAmount = maxAllowed;
                this.numberBuffer.set(maxAllowed.toString());
                this.popup.add(ErrorPopup, {
                    title: _t("Amount limited"),
                    body: _t(
                        "This payment method cannot exceed the order balance. Amount set to %s.",
                        this.env.utils.formatCurrency(maxAllowed)
                    ),
                });
            }
        }

        // Pasar el monto resuelto (o el original si no aplica el límite) al padre
        const amountToPass = method?.limit_closing_cash_to_balance ? resolvedAmount : amount;
        return super.updateSelectedPaymentline(
            amountToPass === false ? false : amountToPass
        );
    },
});
