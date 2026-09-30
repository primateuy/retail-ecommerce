import { _t } from "@web/core/l10n/translation";
import { router } from "@web/core/browser/router";
import { registry } from "@web/core/registry";

/**
 * Cuando el hilo ITD termina, el servidor avisa por el bus al partner del
 * usuario que pulsó «Crear transacción». Si sigue viendo el MISMO pago, se
 * recarga el registro; si está en otra pantalla, sólo se avisa y no se le
 * interrumpe la navegación.
 *
 * 19.0, medido en el navegador: en un pago recién CREADO y guardado,
 * `currentController.props.resId` sigue en `false` (el id nuevo lo tiene el
 * router). Por eso el pago se reconoce también por `router.current.resId`, y
 * en ese caso se recarga con `switchView` y no con `soft_reload`: restaurar
 * el controlador con `resId: false` abriría un pago vacío. El servicio viejo
 * que escuchaba `fiserv_account.payment_updated` no se portó: nadie emitía
 * ese evento.
 */
function openPaymentId(action) {
    const props = action.currentController?.props;
    if (props?.resModel !== "account.payment") {
        return { id: null, fromProps: false };
    }
    if (props.resId) {
        return { id: Number(props.resId), fromProps: true };
    }
    const routed = router.current?.resId;
    return { id: routed ? Number(routed) : null, fromProps: false };
}

export const accountPaymentFiservRefreshService = {
    dependencies: ["bus_service", "action", "notification"],

    start(env, { bus_service, action, notification }) {
        bus_service.subscribe("fiserv_account.payment_refresh", async (payload) => {
            const pid = Number(payload?.payment_id);
            if (payload?.message) {
                notification.add(payload.message, {
                    title: _t("Fiserv ITD"),
                    type: payload?.posted ? "success" : "warning",
                    sticky: !payload?.posted,
                });
            }
            const open = openPaymentId(action);
            if (!pid || open.id !== pid) {
                return;
            }
            try {
                if (open.fromProps) {
                    await action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
                } else {
                    await action.switchView("form", { resId: pid });
                }
            } catch (e) {
                console.warn("Fiserv: no se pudo recargar el pago", e);
            }
        });
        // Mismo patrón que calendar_notification_service: arrancar el bus es
        // idempotente y no depender de que otro servicio lo haya hecho.
        bus_service.start();
    },
};

registry.category("services").add("account_payment_fiserv_refresh", accountPaymentFiservRefreshService);
