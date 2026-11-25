import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { patch } from "@web/core/utils/patch";

patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        if (!(await super.isOrderValid(...arguments))) {
            return false;
        }
        // Segunda barrera: cubre el cambio de cliente dentro de la pantalla de
        // pago y la validacion rapida, que no pasan por pay().
        return this.pos.checkFeAmountLimit(this.order);
    },
});
