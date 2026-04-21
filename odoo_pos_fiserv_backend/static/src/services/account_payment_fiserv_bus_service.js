/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

/**
 * Comprueba si el usuario sigue en el formulario del mismo account.payment.
 * En Odoo 17 el act_window guarda resModel/resId en controller.props (no en la raíz).
 * Respaldo: hash del router (#model=…&id=…).
 */
function isAccountPaymentFormOpen(action, router, paymentId) {
    if (paymentId == null) {
        return false;
    }
    const ctrl = action.currentController;
    const props = ctrl?.props;
    if (
        props?.resModel === "account.payment" &&
        Number(props.resId) === Number(paymentId)
    ) {
        return true;
    }
    const h = router.current?.hash;
    return (
        h?.model === "account.payment" && Number(h.id) === Number(paymentId)
    );
}

/**
 * Escucha el bus tras un cobro Fiserv async desde account.payment: aviso al usuario
 * y soft_reload del formulario si sigue abierto el mismo registro (sin F5 manual).
 */
export const accountPaymentFiservBusService = {
    dependencies: ["bus_service", "action", "notification", "router"],

    start(env, { bus_service, action, notification, router }) {
        bus_service.subscribe("fiserv_account.payment_updated", async (payload) => {
            const pid = payload?.payment_id;
            const msg = payload?.message;
            const posted = Boolean(payload?.posted);
            if (msg) {
                notification.add(msg, {
                    title: _t("Fiserv ITD"),
                    type: posted ? "success" : "warning",
                    sticky: false,
                });
            }
            if (!isAccountPaymentFormOpen(action, router, pid)) {
                return;
            }
            const ctrl = action.currentController;
            if (ctrl?.jsId) {
                await action.restore(ctrl.jsId);
            } else {
                await action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
            }
        });
        bus_service.start();
    },
};

registry.category("services").add("account_payment_fiserv_bus", accountPaymentFiservBusService);
