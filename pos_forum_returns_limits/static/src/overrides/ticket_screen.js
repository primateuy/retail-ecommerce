/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

const { DateTime } = luxon;
const originalOnDoRefund = TicketScreen.prototype.onDoRefund;

patch(TicketScreen.prototype, {
    async onDoRefund() {
        // Obtener la orden seleccionada para validar antigüedad
        const order = this.getSelectedOrder();

        // Verificar el límite de días configurado en el POS
        const limitDays = this.pos.config.refund_days_limit || 0;
        if (limitDays > 0 && order) {
            // Normalizar la fecha de la orden a DateTime de luxon
            const orderDate = order.date_order;
            const orderDateTime = DateTime.isDateTime(orderDate)
                ? orderDate
                : DateTime.fromISO(orderDate || "");

            // Calcular días transcurridos desde la fecha de la orden
            const daysDiff = Math.floor(DateTime.now().diff(orderDateTime, "days").days);
            if (Number.isFinite(daysDiff) && daysDiff > limitDays) {
                this.popup.add(ErrorPopup, {
                    title: _t("Refund Not Allowed"),
                    body: _t(
                        "This order exceeds the refund limit of %s day(s).",
                        limitDays
                    ),
                });
                return;
            }
        }

        // Ejecutar el flujo estándar de reembolso
        return await originalOnDoRefund.apply(this, arguments);
    },
});
