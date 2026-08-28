/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { Order } from "@point_of_sale/app/store/models";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";

patch(Order.prototype, {
    async pay() {
        // Bloquear el paso a la pantalla de pago si el cliente (o, cuando la
        // orden no tiene cliente, el cliente por defecto configurado en el
        // POS) tiene control de monto máximo permitido FE activo y la venta
        // lo supera.
        const partner = this.get_partner() || this._getDefaultPaymentCustomer();
        if (partner && partner.pos_fe_amount_limit_control) {
            const maxAmount = partner.pos_fe_max_amount_company_currency || 0;
            const orderTotal = this.get_total_with_tax();
            if (orderTotal > maxAmount) {
                await this.env.services.popup.add(ErrorPopup, {
                    title: _t("COMPRA MAYOR A %s", this.env.utils.formatCurrency(maxAmount)),
                    body: _t(
                        "El total de la venta es mayor a %s. Se necesita identificar al cliente." +
                            "Cargue un cliente con documento válido.",
                        this.env.utils.formatCurrency(maxAmount)
                    ),
                });
                return;
            }
        }

        // Ejecutar el flujo estándar de pago
        return super.pay(...arguments);
    },

    /**
     * Resuelve el cliente por defecto de pago configurado en pos.config
     * (módulo pos_forum_payment_default_customer) para usarlo en la
     * validación de monto máximo cuando la orden no tiene cliente asignado.
     * Devuelve undefined si ese módulo no está instalado o no hay cliente
     * por defecto configurado.
     */
    _getDefaultPaymentCustomer() {
        const defaultCustomerId = this.pos.config.payment_default_customer_id;
        if (!defaultCustomerId) {
            return undefined;
        }
        // Soporte para valor numérico o [id, name] según cómo envíe el backend
        const partnerId = Array.isArray(defaultCustomerId) ? defaultCustomerId[0] : defaultCustomerId;
        return partnerId ? this.pos.db.get_partner_by_id(partnerId) : undefined;
    },
});
