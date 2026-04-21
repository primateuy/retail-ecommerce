/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

/**
 * Tras action_post en hilo (Fiserv ITD), el servidor envía un bus al partner del usuario.
 * Recarga el formulario con la acción cliente estándar ``soft_reload`` (web.client_actions).
 */
function sameAccountPaymentForm(action, router, paymentId) {
    if (paymentId == null) {
        return false;
    }
    const props = action.currentController?.props;
    if (props?.resModel === "account.payment" && Number(props.resId) === Number(paymentId)) {
        return true;
    }
    const h = router.current?.hash;
    return h?.model === "account.payment" && Number(h.id) === Number(paymentId);
}

export const accountPaymentFiservRefreshService = {
    dependencies: ["bus_service", "action", "notification", "router"],

    start(env, { bus_service, action, notification, router }) {
        bus_service.subscribe("fiserv_account.payment_refresh", async (payload) => {
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
            if (!sameAccountPaymentForm(action, router, pid)) {
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

registry.category("services").add("account_payment_fiserv_refresh", accountPaymentFiservRefreshService);
