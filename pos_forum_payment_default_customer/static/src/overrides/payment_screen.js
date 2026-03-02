/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { onMounted } from "@odoo/owl";

/**
 * Aplica el cliente por defecto configurado en el POS al entrar a la pantalla de pago
 * cuando la orden no tiene cliente asignado (comportamiento 4.D del documento PDV).
 * Compatible con bi_pos_default_customer: ese módulo asigna cliente al crear la orden;
 * este asigna al pasar a pagar si aún no hay cliente.
 */
patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this._applyPaymentDefaultCustomer());
    },

    /**
     * Asigna el cliente por defecto de pago a la orden actual si no tiene cliente.
     * Se ejecuta al montar la pantalla de pago.
     */
    _applyPaymentDefaultCustomer() {
        const order = this.currentOrder;
        if (!order) {
            return;
        }

        // No sobrescribir si la orden ya tiene cliente
        if (order.get_partner && order.get_partner()) {
            return;
        }

        const config = this.pos.config;
        const defaultCustomerId = config.payment_default_customer_id;
        if (!defaultCustomerId) {
            return;
        }

        // Soporte para valor numérico o [id, name] según cómo envíe el backend
        const partnerId = Array.isArray(defaultCustomerId)
            ? defaultCustomerId[0]
            : defaultCustomerId;
        if (!partnerId) {
            return;
        }

        const partner = this.pos.db.get_partner_by_id(partnerId);
        if (partner && order.set_partner) {
            order.set_partner(partner);
        }
    },
});
