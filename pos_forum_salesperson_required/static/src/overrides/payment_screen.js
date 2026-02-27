/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async _isOrderValid(isForceValidate) {
        // Validar vendedor de la orden antes de continuar
        const order = this.currentOrder;
        const orderSalesperson = order.get_order_salesperson?.();
        if (!orderSalesperson) {
            this.popup.add(ErrorPopup, {
                title: _t("Missing Salesperson"),
                body: _t("Please select a salesperson for the order before paying."),
            });
            return false;
        }

        // Asignar vendedor de la orden a líneas faltantes
        order.apply_order_salesperson_to_lines?.();

        // Validar que no queden líneas sin vendedor
        if (order.has_line_without_salesperson?.()) {
            this.popup.add(ErrorPopup, {
                title: _t("Missing Salesperson"),
                body: _t("All order lines must have a salesperson before paying."),
            });
            return false;
        }

        // Ejecutar la validación estándar del POS
        return await super._isOrderValid(...arguments);
    },
});
