/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { formatCurrency } from "@web/core/currency";
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
            // La comparación usa el monto ya convertido a moneda de la compañía
            // por el backend, porque el total de la orden está en esa moneda.
            const maxAmount = partner.pos_fe_max_amount_company_currency || 0;
            const orderTotal = this.get_total_with_tax();
            if (orderTotal > maxAmount) {
                const maxAmountLabel = this._formatPosFeMaxAmount(partner);
                await this.env.services.popup.add(ErrorPopup, {
                    title: _t("COMPRA MAYOR A %s", maxAmountLabel),
                    body: _t(
                        "El total de la venta es mayor a %s. Se necesita identificar al cliente." +
                            "Cargue un cliente con documento válido.",
                        maxAmountLabel
                    ),
                });
                return;
            }
        }

        // Ejecutar el flujo estándar de pago
        return super.pay(...arguments);
    },

    /**
     * Formatea el monto máximo permitido en la moneda configurada en la ficha
     * del cliente (``pos_fe_max_amount_currency_id``), para que el cajero vea
     * el mismo valor y símbolo que se cargó en el backend.
     *
     * Se usa ``formatCurrency`` de ``@web/core/currency`` en lugar de
     * ``env.utils.formatCurrency`` porque este último formatea siempre con la
     * moneda del POS y no admite otra.
     *
     * Si el cliente no tiene moneda asignada, se muestra el monto convertido
     * a moneda de la compañía con el formato por defecto del POS.
     */
    _formatPosFeMaxAmount(partner) {
        const currencyField = partner.pos_fe_max_amount_currency_id;
        const currencyId = Array.isArray(currencyField) ? currencyField[0] : currencyField;
        if (!currencyId) {
            return this.env.utils.formatCurrency(partner.pos_fe_max_amount_company_currency || 0);
        }
        return formatCurrency(partner.pos_fe_max_amount || 0, currencyId);
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
