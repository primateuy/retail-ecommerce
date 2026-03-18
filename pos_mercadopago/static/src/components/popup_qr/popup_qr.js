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

    async onComprobar() {
        this.state.checking = true;
        try {
            const result = await this.orm.searchRead(
                "pos.order",
                [["name", "=", this.orderReference]],
                ["name", "state"]
            );

            if (result.length === 0) {
                this.notification.add("La orden aun sigue sin recibir el pago", {
                    type: "warning",
                });
                return;
            }

            const frontendOrder = this.pos.get_order();
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
                this.pos.mpQrPanel = null;
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
