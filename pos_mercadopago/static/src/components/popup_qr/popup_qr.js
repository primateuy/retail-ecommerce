/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";

export class MercadoPagoQRPanel extends Component {
    static template = "pos_mercadopago.MercadoPagoQRPanel";

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ checking: false, cancelling: false, confirmForce: false });
    }

    get qrSrc() {
        return this.pos.mpQrPanel?.qrSrc;
    }

    get orderReference() {
        return this.pos.mpQrPanel?.orderReference;
    }

    get isBusy() {
        return this.state.checking || this.state.cancelling;
    }

    clearPendingState(order) {
        if (!order) {
            return;
        }
        if (order.clearMpPendingOrder) {
            order.clearMpPendingOrder();
        } else {
            order.mp_pending_order = null;
            order.save_to_db?.();
        }
    }

    /**
     * Cierra la orden en el POS cuando el pedido ya quedó registrado en Odoo.
     *
     * @param {string} [message] aviso a mostrar (por ejemplo, pedido en borrador).
     */
    finalizePaidOrder(message) {
        if (message) {
            this.notification.add(message, { type: "warning" });
        }
        const frontendOrder = this.pos.get_order();
        this.clearPendingState(frontendOrder);
        frontendOrder.finalized = true;
        this.pos.db.remove_unpaid_order(frontendOrder);
        this.pos.mpQrPanel = null;
        this.pos.showScreen("ReceiptScreen");
    }

    /**
     * Saca el QR de la orden en el POS y vuelve a la pantalla de pago.
     *
     * Solo toca el estado local: no borra nada en Odoo ni en Mercado Pago.
     */
    releaseOrderLocally() {
        const frontendOrder = this.pos.get_order();
        this.clearPendingState(frontendOrder);
        this.pos.mpQrPanel = null;
        const mpLines = frontendOrder.paymentlines.filter(
            (line) => line.payment_method.use_payment_terminal === "mercado_pago"
        );
        for (const line of mpLines) {
            frontendOrder.remove_paymentline(line);
        }
        this.pos.showScreen("PaymentScreen");
    }

    /**
     * Salida de emergencia cuando Cancelar/Eliminar fallan (QR vencido que MP no
     * deja borrar, MP caído, error del servidor). Pide confirmación en el mismo
     * panel porque los popups del POS quedan debajo del overlay.
     *
     * No borra la orden pendiente del servidor: si el cliente había pagado, el
     * webhook igual registra el pedido y queda trazado.
     */
    onForzarCierre() {
        if (!this.state.confirmForce) {
            this.state.confirmForce = true;
            return;
        }
        console.warn("Cierre forzado del QR de Mercado Pago", this.orderReference);
        this.state.confirmForce = false;
        this.releaseOrderLocally();
        this.notification.add(
            `QR ${this.orderReference || ""} cerrado sin verificar. Si el cliente pago, revise la orden en el backend antes de volver a cobrar.`,
            { type: "warning", sticky: true }
        );
    }

    onCancelarForzado() {
        this.state.confirmForce = false;
    }

    async requestCancel() {
        const result = await this.pos.orm.rpc("/pos/delete-order", {
            external_id: this.pos.store_till?.external_id,
            user_id: this.pos.store_till?.user_id_mp,
            order_reference: this.orderReference,
        });
        return JSON.parse(result);
    }

    async onComprobar() {
        this.state.checking = true;
        try {
            const result = await this.pos.orm.rpc("/pos/check-mp-order-status", {
                order_reference: this.orderReference,
            });
            const parsed = JSON.parse(result);

            if (parsed.status === "paid") {
                this.finalizePaidOrder(parsed.message);
                return;
            }

            const messages = {
                pending: ["La orden aun sigue sin recibir el pago", "warning"],
                expired: [
                    "El QR esta vencido. Use 'Cancelar QR y volver' para cobrar de nuevo.",
                    "warning",
                ],
                processing: ["El pago fue recibido y Odoo aun lo esta procesando.", "info"],
                error: ["No se pudo consultar Mercado Pago, intente de nuevo.", "danger"],
                not_found: [
                    "No se encontro la orden en Odoo. Use 'Cancelar QR y volver' para liberar la caja.",
                    "danger",
                ],
            };
            const [message, type] = messages[parsed.status] || messages.error;
            this.notification.add(message, { type });
        } catch (err) {
            console.error("Error al comprobar pago", err);
            this.notification.add("Hubo un error al comprobar el pago", { type: "danger" });
        } finally {
            this.state.checking = false;
        }
    }

    /**
     * Cancela el QR y vuelve a la pantalla de pago conservando la orden,
     * para poder cobrarla con otro medio.
     */
    async onCancelarQr() {
        this.state.cancelling = true;
        try {
            const parsed = await this.requestCancel();
            if (parsed.status === "paid") {
                this.finalizePaidOrder(parsed.message);
                return;
            }
            if (parsed.error !== false) {
                this.notification.add(parsed.message || "No se pudo cancelar el QR", {
                    type: "danger",
                });
                return;
            }
            this.releaseOrderLocally();
        } catch (err) {
            console.error("Error al cancelar el QR", err);
            this.notification.add("Hubo un error al cancelar el QR", { type: "danger" });
        } finally {
            this.state.cancelling = false;
        }
    }

    async onEliminar() {
        this.state.cancelling = true;
        try {
            const parsed = await this.requestCancel();
            if (parsed.status === "paid") {
                this.finalizePaidOrder(parsed.message);
                return;
            }
            if (parsed.error === false) {
                const frontendOrder = this.pos.get_order();
                this.clearPendingState(frontendOrder);
                this.pos.mpQrPanel = null;
                this.pos.removeOrder(frontendOrder, false);
                const orderList = this.pos.get_order_list();
                if (orderList.length > 0) {
                    this.pos.set_order(orderList[0]);
                } else {
                    this.pos.add_new_order();
                }
                this.pos.showScreen("ProductScreen");
            } else {
                this.notification.add(parsed.message || "Error al eliminar la orden", {
                    type: "danger",
                });
            }
        } catch (err) {
            console.error("Error al eliminar orden", err);
            this.notification.add("Hubo un error al eliminar la orden", { type: "danger" });
        } finally {
            this.state.cancelling = false;
        }
    }
}
