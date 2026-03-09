/** @odoo-module */

/**
 * Maneja pagos de órdenes sincronizadas provenientes de otros POS/compañías.
 *
 * Cuando se amplía la búsqueda de órdenes (pos_forum_order_search_expand),
 * pueden aparecer pagos cuyo `payment_method_id` no está configurado en el
 * POS actual. En el core, `Payment.init_from_JSON` asume que siempre existe
 * `this.pos.payment_methods_by_id[id]` y rompe con:
 *
 *   TypeError: Cannot read properties of undefined (reading 'name')
 *
 * Este patch vuelve tolerante ese caso:
 * - Si el método de pago no está cargado en la sesión actual,
 *   se crea un método de pago sintético con un nombre genérico.
 * - De esta forma, las órdenes se pueden visualizar y reembolsar
 *   sin depender de que todos los métodos de pago estén configurados
 *   en el POS actual.
 */

import { Payment } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(Payment.prototype, {
    init_from_JSON(json) {
        // Mismo comportamiento base, pero tolerando métodos de pago desconocidos.
        this.amount = json.amount;

        const method =
            this.pos?.payment_methods_by_id?.[json.payment_method_id] || null;

        if (method) {
            this.payment_method = method;
            this.name = this.payment_method.name || _t("Payment");
        } else {
            // Método de pago no cargado en la sesión actual: crear fallback
            this.payment_method = {
                id: json.payment_method_id,
                name: _t("External payment"),
                is_forum_unknown_method: true,
            };
            this.name = this.payment_method.name;
        }

        this.can_be_reversed = json.can_be_reversed;
        this.payment_status = json.payment_status;
        this.ticket = json.ticket;
        this.card_type = json.card_type;
        this.cardholder_name = json.cardholder_name;
        this.transaction_id = json.transaction_id;
        this.is_change = json.is_change;
    },
});

