/** @odoo-module */

/**
 * Pantalla de pago: impide validar el pedido si hay líneas de método manual
 * sin datos del popup completos (mismas reglas que el popup: campos required).
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { sprintf } from "@web/core/utils/strings";

patch(PaymentScreen.prototype, {
    /**
     * Antes de las validaciones estándar, comprueba líneas de pago manual.
     */
    async _isOrderValid(isForceValidate) {
        const check = this._forumValidateManualPaymentLines();
        if (!check.ok) {
            console.debug(
                "[FORUM manual POS] Validación pedido bloqueada: %s",
                check.message
            );
            this.popup.add(ErrorPopup, {
                title: _t("Datos de transacción manual"),
                body: check.message,
            });
            return false;
        }
        const result = await super._isOrderValid(...arguments);
        if (result) {
            console.debug(
                "[FORUM manual POS] Validación de pedido OK (incl. datos manuales)."
            );
        }
        return result;
    },

    /**
     * Verifica que cada línea con método manual tenga los valores requeridos.
     *
     * Replica la lógica de obligatoriedad del ManualPaymentPopup para no poder
     * pagar sin completar el formulario.
     */
    _forumValidateManualPaymentLines() {
        const order = this.currentOrder;
        if (!order) {
            return { ok: true };
        }
        const lines = order.get_paymentlines();
        for (const line of lines) {
            const pm = line.payment_method;
            if (!pm || !pm.manual_transaction_enabled) {
                continue;
            }
            if (line.is_change) {
                continue;
            }
            if (line.get_amount() === 0) {
                continue;
            }
            let fields = [];
            try {
                fields = JSON.parse(pm.manual_payment_popup_config || "[]");
            } catch {
                fields = [];
            }
            const values = line.get_manual_payment_values
                ? line.get_manual_payment_values()
                : {};
            for (const field of fields) {
                if (!field.required) {
                    continue;
                }
                const v = values[field.code];
                const empty =
                    v === undefined ||
                    v === null ||
                    v === false ||
                    (typeof v === "string" && v.trim() === "");
                if (empty) {
                    return {
                        ok: false,
                        message: sprintf(
                            _t(
                                "Complete los datos de transacción manual para el método «%s» (campo obligatorio: %s)."
                            ),
                            pm.name,
                            field.label
                        ),
                    };
                }
            }
        }
        return { ok: true };
    },
});
