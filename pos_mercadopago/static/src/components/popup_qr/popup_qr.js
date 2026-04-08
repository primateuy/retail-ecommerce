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
        this.state = useState({ checking: false, cancelling: false });
    }

    get qrSrc() {
        return this.pos.mpQrPanel?.qrSrc;
    }

    get orderReference() {
        return this.pos.mpQrPanel?.orderReference;
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

    async onComprobar() {
        this.state.checking = true;
        try {
            const result = await this.pos.orm.rpc("/pos/check-mp-order-status", {
                order_reference: this.orderReference,
            });
            const parsed = JSON.parse(result);

            if (parsed.status === "pending") {
                this.notification.add("La orden aun sigue sin recibir el pago", {
                    type: "warning",
                });
                return;
            }

            if (parsed.status === "expired") {
                this.notification.add("La orden esta vencida.", {
                    type: "warning",
                });
                return;
            }

            if (parsed.status === "processing") {
                this.notification.add("El pago fue recibido y Odoo aun lo esta procesando.", {
                    type: "info",
                });
                return;
            }

            if (parsed.status === "not_found") {
                this.notification.add("No se encontro la orden en Odoo ni en Mercado Pago.", {
                    type: "danger",
                });
                return;
            }

            const frontendOrder = this.pos.get_order();
            this.clearPendingState(frontendOrder);
            frontendOrder.finalized = true;
            this.pos.db.remove_unpaid_order(frontendOrder);
            this.pos.mpQrPanel = null;
            this.pos.showScreen("ReceiptScreen");
        } catch (err) {
            console.error("Error al comprobar pago", err);
            this.notification.add("Hubo un error al comprobar el pago", { type: "danger" });
        } finally {
            this.state.checking = false;
        }
    }

    async onEliminar() {
        this.state.cancelling = true;
        try {
            const result = await this.pos.orm.rpc("/pos/delete-order", {
                external_id: this.pos.store_till.external_id,
                user_id: this.pos.store_till.user_id_mp,
                order_reference: this.orderReference,
            });

            const parsed = JSON.parse(result);
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
                    type: parsed.status === "expired" ? "warning" : "danger",
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
