/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

/**
 * Tras la aprobación de la transacción OCA POSLink en el hilo ITD, el servidor
 * envía un bus al partner del usuario. Si el usuario sigue viendo el MISMO
 * form de account.payment, refrescamos el record; si está en otra vista o
 * en otro pago, solo notificamos y no interrumpimos su navegación.
 *
 * Importante: NO usar ``soft_reload`` ni ``action.restore`` porque en Odoo 17
 * terminan cerrando el form actual y abriendo un create() nuevo. En su lugar
 * se hace ``doAction`` apuntando explícitamente al ``res_id`` actual, lo que
 * fuerza re-lectura del record sin salir del form.
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

export const accountPaymentOCARefreshService = {
    dependencies: ["bus_service", "action", "notification", "router"],

    start(env, { bus_service, action, notification, router }) {
        bus_service.subscribe("oca_account.payment_refresh", async (payload) => {
            const pid = payload?.payment_id;
            const msg = payload?.message;
            const posted = Boolean(payload?.posted);
            if (msg) {
                notification.add(msg, {
                    title: _t("OCA POSLink"),
                    type: posted ? "success" : "warning",
                    sticky: false,
                });
            }
            if (!sameAccountPaymentForm(action, router, pid)) {
                return;
            }
            // Abrir el mismo pago con res_id explícito para forzar re-lectura.
            // Odoo reutiliza el controller si ya está mostrando ese record.
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
                console.warn("OCA refresh: doAction falló, se omite recarga", e);
            }
        });
        bus_service.start();
    },
};

registry.category("services").add("account_payment_oca_refresh", accountPaymentOCARefreshService);
