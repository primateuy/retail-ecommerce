import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError } from "@web/core/network/rpc";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    /**
     * Verifica el monto maximo FE del cliente para el pedido.
     * Si la venta lo supera, ofrece seleccionar otro cliente.
     *
     * @param {Object} order pedido a controlar
     * @returns {Promise<boolean>} true si se puede seguir cobrando
     */
    async checkFeAmountLimit(order) {
        // Si el control esta habilitado lo decide el servidor: la config cacheada
        // en el navegador puede no traer el campo si el POS se abrio antes de
        // instalar el modulo.
        if (order.isRefund) {
            return true;
        }
        let requirement;
        try {
            requirement = await this.data.call("pos.order", "get_fe_amount_limit_requirement", [
                this.config.id,
                order.getPartner()?.id || false,
                order.priceExcl,
            ]);
        } catch (error) {
            // Sin conexion no se puede controlar; la emision del CFE vuelve a
            // validar, y bloquear toda venta offline seria peor.
            if (error instanceof ConnectionLostError) {
                return true;
            }
            throw error;
        }
        if (!requirement.blocked) {
            return true;
        }
        const confirmed = await ask(this.dialog, {
            title: requirement.title,
            body: requirement.message,
            confirmLabel: _t("Select customer"),
            cancelLabel: _t("Back"),
        });
        if (confirmed) {
            await this.selectPartner(order);
        }
        return false;
    },

    async pay() {
        // Se controla antes de entrar a pago para que no se llegue a cobrar
        // con una terminal una venta que despues no se puede emitir.
        const order = this.getOrder();
        if (order && !(await this.checkFeAmountLimit(order))) {
            return;
        }
        return super.pay(...arguments);
    },
});
