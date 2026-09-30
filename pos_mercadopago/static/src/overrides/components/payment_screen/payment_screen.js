/** @odoo-module **/
import { PaymentMercadoPago } from "@pos_mercado_pago/app/payment_mercado_pago";
import { MercadoPagoQRPanel } from "@pos_mercadopago/components/popup_qr/popup_qr";
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { floatIsZero } from "@web/core/utils/numbers";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

patch(PaymentScreen, {
    components: {
        ...PaymentScreen.components,
        MercadoPagoQRPanel,
    },
});

patch(ProductScreen, {
    components: {
        ...(ProductScreen.components || {}),
        MercadoPagoQRPanel,
    },
});

export class PaymentMercadoPagoQR extends PaymentMercadoPago {
    async setup() {
        super.setup(...arguments);
        this.set_store_till();
    }

    async set_store_till() {
        const result = await this.env.services.orm.silent.call(
            "store.tills",
            "get_store_till_by_id",
            [[this.pos.config.mp_tills[0]]]
        );
        this.pos.store_till = result.till;
        this.pos.qr_type = result.qr_type;
    }

    // override
    async send_payment_request(cid) {
        const orderFrontend = this.pos.get_order();

        if (this.pos.qr_type === "dynamic" && orderFrontend.paymentlines.length > 1) {
            return this._showMsg(
                "Cuando la modalidad del QR de Mercado Pago es dinamico, la orden debe ser pagada completamente por este metodo de pago",
                "| Validacion de Antes de Crear la Orden"
            );
        }

        const isMercadoPagoSelected = orderFrontend.paymentlines.some(
            (line) => line.payment_method.id === this.payment_method.id
        );

        if (!isMercadoPagoSelected) {
            return;
        }

        // Si ya hay un QR pendiente para esta orden se vuelve a mostrar en vez de generar otro,
        // porque un segundo QR en la misma caja pisa al primero en Mercado Pago.
        if (orderFrontend.mp_pending_order) {
            this.pos._syncMercadoPagoPanelWithOrder(orderFrontend);
            return;
        }

        const amountError = this._checkMercadoPagoAmount(orderFrontend, cid);
        if (amountError) {
            return this._showMsg(amountError, "| Validacion de montos");
        }

        try {
            const paymentLines = this.get_paymentlines(orderFrontend.paymentlines);

            const posOrders = orderFrontend.orderlines.map((line) => ({
                id: line.id,
                title: line.full_product_name,
                currency_id: this.pos.currency?.name || "UYU",
                unit_price: line.price,
                quantity: line.quantity,
                discount: line.discount || 0,
                description: line.product?.description || line.full_product_name,
                product_id: line.product.id,
                tax_ids: line.tax_ids || line.product.taxes_id,
                tax_ids_after_fiscal_position: line.tax_ids || line.product.taxes_id,
                standard_price: line.product.standard_price,
            }));

            const order = await this.pos.orm.rpc("/pos/create-order", {
                store_till_id: this.pos.store_till.id,
                items: posOrders,
                session_id: this.pos.pos_session.id,
                user_id: this.pos.get_cashier_user_id() || this.pos.user.id,
                employee_id: this.pos.cashier?.id || false,
                partner_id: orderFrontend.partner?.id || false,
                cashier_id:
                    orderFrontend.order_salesperson?.id ||
                    this.pos.get_cashier?.()?.id ||
                    false,
                company_id: this.pos.config.company_id[0],
                qr_type: this.pos.qr_type,
                paymentLines: paymentLines,
                amount_total: orderFrontend.get_total_with_tax(),
                amount_return: orderFrontend.get_change(),
            });

            const parsedOrder = JSON.parse(order);
            if (parsedOrder.error) {
                return this._showMsg(parsedOrder.message, "| Error al crear la orden");
            }

            const qrSrc =
                this.pos.qr_type === "static"
                    ? this.pos.store_till.qr_url
                    : parsedOrder.data.qr_data;

            const pendingData = {
                qrSrc: qrSrc,
                orderReference: parsedOrder.order_reference,
                qrType: this.pos.qr_type,
            };
            if (orderFrontend.setMpPendingOrder) {
                orderFrontend.setMpPendingOrder(pendingData);
            } else {
                orderFrontend.mp_pending_order = pendingData;
                orderFrontend.save_to_db?.();
            }
            this.pos.mpQrPanel = pendingData;
        } catch (error) {
            console.error("Error al procesar la orden", error);
            return this._showMsg("Hubo un error al procesar la orden", "| Error al procesar la orden");
        }
    }

    /**
     * Valida que el QR se genere con la orden completamente cubierta.
     *
     * Si se envía MP antes de cargar los demás medios, o si MP supera el saldo,
     * lo cobrado no coincide con el pedido que se registra al confirmar el pago.
     *
     * @param {Order} order orden actual del POS.
     * @param {string} cid cid de la línea de pago de Mercado Pago.
     * @returns {string|false} mensaje de error, o false si los montos son válidos.
     */
    _checkMercadoPagoAmount(order, cid) {
        const decimals = this.pos.currency.decimal_places;
        const mpLine = order.paymentlines.find((line) => line.cid === cid);
        if (!mpLine || mpLine.amount <= 0 || floatIsZero(mpLine.amount, decimals)) {
            return "El monto a cobrar con Mercado Pago debe ser mayor a cero";
        }
        // No se usa order.get_due(): solo suma líneas en estado 'done', y la de MP
        // recién pasa a 'waiting' al enviarse, así que la orden nunca parecía paga.
        const total = order.get_total_with_tax();
        const allPaid = order.paymentlines.reduce((sum, line) => sum + line.amount, 0);
        const due = total - allPaid;
        if (due > 0 && !floatIsZero(due, decimals)) {
            return "Cargue primero los demas medios de pago: la orden debe quedar paga completa antes de generar el QR de Mercado Pago";
        }
        const otherPaid = allPaid - mpLine.amount;
        const remaining = Math.max(total - otherPaid, 0);
        const excess = mpLine.amount - remaining;
        if (excess > 0 && !floatIsZero(excess, decimals)) {
            return "El monto de Mercado Pago supera el saldo pendiente de la orden";
        }
        return false;
    }

    get_paymentlines(paymentlines = []) {
        return paymentlines.map((line) => ({
            amount: line.amount,
            name: line.name,
            payment_method_id: line.payment_method.id,
            is_mercado_pago: line.payment_method.id === this.payment_method.id,
        }));
    }
}

register_payment_method("mercado_pago", PaymentMercadoPagoQR);
