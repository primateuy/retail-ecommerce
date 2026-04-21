/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

/**
 * Tras la aprobación de la transacción Fiserv ITD en el hilo, el servidor
 * envía un bus al partner del usuario. Si el usuario sigue viendo el MISMO
 * form de account.payment, refrescamos el record; si está en otra vista o
 * en otro pago, solo notificamos y no interrumpimos su navegación.
 *
 * Importante: NO usar ``soft_reload`` ni ``action.restore`` porque en Odoo 17
 * terminan cerrando el form actual y abriendo un create() nuevo. En su lugar
 * se hace ``doAction`` apuntando explícitamente al ``res_id`` actual.
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
            try {
                await action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "account.payment",
                    res_id: Number(pid),
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "current",
                });
            } catch (e) {
                console.warn("Fiserv refresh: doAction falló, se omite recarga", e);
            }
        });
        bus_service.start();
    },
};

registry.category("services").add("account_payment_fiserv_refresh", accountPaymentFiservRefreshService);
