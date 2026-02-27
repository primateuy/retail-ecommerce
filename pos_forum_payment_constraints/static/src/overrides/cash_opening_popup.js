/** @odoo-module */

import { CashOpeningPopup } from "@point_of_sale/app/store/cash_opening_popup/cash_opening_popup";
import { patch } from "@web/core/utils/patch";

/**
 * Busca el nodo raíz del popup de apertura (clases estándar del POS).
 */
function getOpeningCashPopupRoot() {
    return (
        document.querySelector(".popup.opening-cash-control") ||
        document.querySelector(".opening-cash-control") ||
        document.querySelector("[class*='opening-cash']") ||
        document.querySelector(".cash-input-sub-section")?.closest(".popup") ||
        document.querySelector(".cash-input-sub-section")?.closest("[class*='modal']")
    );
}

/**
 * Obtiene el input de efectivo de apertura dentro de un nodo raíz.
 */
function findOpeningCashInput(root) {
    if (!root || !root.querySelector) return null;
    return (
        root.querySelector(".cash-input-sub-section input") ||
        root.querySelector(".opening-cash-section input") ||
        root.querySelector("main input") ||
        root.querySelector('input[type="text"]') ||
        root.querySelector("input:not([type='hidden'])")
    );
}

const LOCKED_ATTR = "data-pos-opening-cash-locked";

/**
 * Fuerza readonly/disabled en el input y bloquea cambios por eventos.
 */
function lockInput(input, lockedValue) {
    if (!input) return;
    const value = lockedValue != null ? String(lockedValue) : (input.value || "");
    input.readOnly = true;
    input.disabled = true;
    input.setAttribute("readonly", "readonly");
    input.style.pointerEvents = "none";
    input.style.backgroundColor = "var(--o-input-bg, #e9ecef)";
    input.setAttribute(LOCKED_ATTR, value);

    if (!input._posOpeningCashLockHandler) {
        const handler = (e) => {
            if (input.getAttribute(LOCKED_ATTR) === null) return;
            e.preventDefault();
            e.stopPropagation();
            input.value = input.getAttribute(LOCKED_ATTR) || value;
        };
        input._posOpeningCashLockHandler = handler;
        input.addEventListener("input", handler, true);
        input.addEventListener("keydown", handler, true);
    }
}

/**
 * Patch de CashOpeningPopup: efectivo de apertura solo lectura cuando el método
 * de pago tiene readonly_opening_cash. Se aplica por DOM (sin cambiar la plantilla)
 * para evitar "Missing template" al no depender de una plantilla heredada.
 */
patch(CashOpeningPopup.prototype, {
    setup() {
        super.setup(...arguments);
        try {
            const methods = this.pos?.payment_methods ?? [];
            const cashMethod = methods.find((pm) => pm && pm.is_cash_count);
            this.isOpeningReadonly = !!(cashMethod && cashMethod.readonly_opening_cash);
        } catch (_e) {
            this.isOpeningReadonly = false;
        }
    },

    mounted() {
        super.mounted?.();
        if (!this.isOpeningReadonly) return;

        const self = this;
        const apply = () => {
            if (!self.isOpeningReadonly) return;
            const target = getOpeningCashPopupRoot();
            const input = findOpeningCashInput(target);
            if (input) lockInput(input, self.state?.openingCash ?? input.value);
        };

        apply();
        setTimeout(apply, 0);
        setTimeout(apply, 50);
        setTimeout(apply, 150);
        setTimeout(apply, 350);

        this._openingCashReadonlyObserver = new MutationObserver(() => apply());
        this._openingCashReadonlyObserver.observe(document.body, {
            childList: true,
            subtree: true,
        });

        let ticks = 0;
        this._openingCashReadonlyInterval = setInterval(() => {
            apply();
            ticks += 1;
            if (ticks >= 100) {
                clearInterval(self._openingCashReadonlyInterval);
                self._openingCashReadonlyInterval = null;
            }
        }, 100);
    },

    willUnmount() {
        if (this._openingCashReadonlyObserver) {
            this._openingCashReadonlyObserver.disconnect();
            this._openingCashReadonlyObserver = null;
        }
        if (this._openingCashReadonlyInterval) {
            clearInterval(this._openingCashReadonlyInterval);
            this._openingCashReadonlyInterval = null;
        }
        super.willUnmount?.();
    },

    patched() {
        super.patched?.(...arguments);
        if (this.isOpeningReadonly) {
            const target = getOpeningCashPopupRoot();
            const input = findOpeningCashInput(target);
            if (input) lockInput(input, this.state?.openingCash ?? input.value);
        }
    },
});
