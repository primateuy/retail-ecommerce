/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { parseFloat } from "@web/views/fields/parsers";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";

const originalSetManualCashInput = ClosePosPopup.prototype.setManualCashInput;

patch(ClosePosPopup.prototype, {
    _getPaymentMethodById(paymentMethodId) {
        try {
            return this.pos?.payment_methods_by_id?.[paymentMethodId] ?? null;
        } catch (_e) {
            return null;
        }
    },

    isClosingMethodReadonly(paymentMethodId) {
        try {
            const paymentMethod = this._getPaymentMethodById(paymentMethodId);
            if (!paymentMethod) return false;
            if (paymentMethod.type === "cash") return false;
            return !!paymentMethod.readonly_closing_non_cash;
        } catch (_e) {
            return false;
        }
    },

    _isCashClosingLimitEnabled() {
        // Verificar si el método efectivo tiene tope de saldo habilitado
        const cashMethodId = this.props.default_cash_details?.id;
        const paymentMethod = cashMethodId ? this._getPaymentMethodById(cashMethodId) : null;
        return !!paymentMethod?.limit_closing_cash_to_balance;
    },

    setManualCashInput(amount) {
        if (typeof originalSetManualCashInput !== "function") {
            return;
        }
        // Validar formato del monto antes de aplicar restricciones
        if (!this.env?.utils?.isValidFloat(amount)) {
            return;
        }

        // Enforce tope de saldo en cierre si está habilitado
        const defaultCash = this.props?.default_cash_details;
        if (defaultCash && this._isCashClosingLimitEnabled()) {
            const expectedAmount = defaultCash.amount ?? 0;
            const parsedAmount = parseFloat(amount);
            if (parsedAmount > expectedAmount && this.state?.payments?.[defaultCash.id]) {
                this.state.payments[defaultCash.id].counted =
                    this.env.utils.formatCurrency(expectedAmount, false);
                this.popup.add(ErrorPopup, {
                    title: _t("Invalid Closing Amount"),
                    body: _t("Counted cash cannot exceed the expected balance."),
                });
                return;
            }
        }

        return originalSetManualCashInput.apply(this, arguments);
    },
});
