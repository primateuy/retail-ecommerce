/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { parseFloat } from "@web/views/fields/parsers";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";

const originalSetManualCashInput = ClosePosPopup.prototype.setManualCashInput;

/**
 * Bloquea un input del popup de cierre (readonly + disabled + evita cambios por eventos).
 */
function lockClosingInput(input, value) {
    if (!input) return;
    const val = value != null ? String(value) : (input.value || "");
    input.value = val;
    input.readOnly = true;
    input.disabled = true;
    input.setAttribute("readonly", "readonly");
    input.style.pointerEvents = "none";
    input.style.backgroundColor = "var(--o-input-bg, #e9ecef)";
    input.setAttribute("data-pos-closing-locked", val);
    if (!input._posClosingLockHandler) {
        const handler = (e) => {
            e.preventDefault();
            e.stopPropagation();
            input.value = input.getAttribute("data-pos-closing-locked") || val;
        };
        input._posClosingLockHandler = handler;
        input.addEventListener("input", handler, true);
        input.addEventListener("keydown", handler, true);
    }
}

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

    mounted() {
        super.mounted?.();
        this._applyClosingReadonlyInputs();
        this._closingReadonlyInterval = setInterval(() => this._applyClosingReadonlyInputs(), 200);
        // Bloquear al recibir foco por si el input se re-renderizó
        this._boundClosingFocusLock = (e) => {
            if (e.target?.tagName !== "INPUT" || !e.target?.closest) return;
            const root = this.el || document.querySelector(".close-pos-popup");
            if (!root?.contains(e.target)) return;
            const tr = e.target.closest("tbody tr");
            if (!tr) return;
            const tbody = tr.closest("tbody");
            if (tbody?.classList.contains("cash-overview")) return;
            const otherMethods = this.props?.other_payment_methods || [];
            const rows = tbody ? Array.from(tbody.querySelectorAll("tr")) : [];
            const idx = rows.indexOf(tr);
            const pm = otherMethods[idx];
            if (pm && this.isClosingMethodReadonly(pm.id)) {
                lockClosingInput(e.target, this.state?.payments?.[pm.id]?.counted);
            }
        };
        document.addEventListener("focusin", this._boundClosingFocusLock, true);
    },

    patched() {
        super.patched?.();
        // Reaplicar bloqueo tras cada actualización del DOM por OWL (evita que se pierda readonly)
        this._applyClosingReadonlyInputs();
    },

    willUnmount() {
        if (this._closingReadonlyInterval) {
            clearInterval(this._closingReadonlyInterval);
            this._closingReadonlyInterval = null;
        }
        if (this._boundClosingFocusLock) {
            document.removeEventListener("focusin", this._boundClosingFocusLock, true);
            this._boundClosingFocusLock = null;
        }
        super.willUnmount?.();
    },

    /**
     * En el popup de cierre, deja en solo lectura los inputs "Counted" de métodos
     * que tienen readonly_closing_non_cash (tipos no efectivo).
     */
    _applyClosingReadonlyInputs() {
        const root = this.el || document.querySelector(".close-pos-popup");
        if (!root) return;
        const otherMethods = this.props?.other_payment_methods || [];
        const tbodies = root.querySelectorAll("tbody");
        // El tbody de "other" tiene una fila por método; no todas las filas tienen input (solo bank con number !== 0)
        let otherTbody = null;
        for (const tbody of tbodies) {
            const rows = tbody.querySelectorAll("tr");
            if (rows.length === otherMethods.length && !tbody.classList.contains("cash-overview")) {
                otherTbody = tbody;
                break;
            }
        }
        if (!otherTbody) return;
        otherTbody.querySelectorAll("tr").forEach((tr, idx) => {
            const pm = otherMethods[idx];
            if (!pm || !this.isClosingMethodReadonly(pm.id)) return;
            const input = tr.querySelector("input");
            const value = this.state?.payments?.[pm.id]?.counted;
            if (input) lockClosingInput(input, value);
        });
    },
});
