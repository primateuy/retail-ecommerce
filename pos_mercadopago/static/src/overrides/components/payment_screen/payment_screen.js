/** @odoo-module **/
import { PaymentMercadoPago } from "@pos_mercado_pago/app/payment_mercado_pago";
import { MercadoPagoQRPanel } from "@pos_mercadopago/components/popup_qr/popup_qr";
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

patch(PaymentScreen, {
    components: {
        ...PaymentScreen.components,
        MercadoPagoQRPanel,
    },
});

export class PaymentMercadoPagoQR extends PaymentMercadoPago {
    async setup() {
        super.setup(...arguments);
        if (this.payment_method.qr_integration) {
            this.set_store_till();
        }
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
        
        if (!this.payment_method.qr_integration) {
            return super.send_payment_request(cid);
        }

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

        try {
            const paymentLines = this.get_paymentlines(orderFrontend.paymentlines);

            const posOrders = orderFrontend.orderlines.map((line) => ({
                id: line.id,
                title: line.full_product_name,
                currency_id: this.pos.currency?.name || "UYU",
                unit_price: line.price,
                quantity: line.quantity,
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
                user_id: this.pos.pos_session.user_id[0],
                partner_id: orderFrontend.partner?.id || false,
                cashier_id:
                    orderFrontend.order_salesperson?.id ||
                    this.pos.get_cashier?.()?.id ||
                    false,
                company_id: this.pos.config.company_id[0],
                qr_type: this.pos.qr_type,
                paymentLines: paymentLines,
            });

            const parsedOrder = JSON.parse(order);
            if (parsedOrder.error) {
                return this._showMsg(parsedOrder.message, "| Error al crear la orden");
            }

            const qrSrc =
                this.pos.qr_type === "static"
                    ? this.pos.store_till.qr_url
                    : parsedOrder.data.qr_data;

            this.pos.mpQrPanel = {
                qrSrc: qrSrc,
                orderReference: parsedOrder.order_reference,
            };
        } catch (error) {
            console.error("Error al procesar la orden", error);
            return this._showMsg("Hubo un error al procesar la orden", "| Error al procesar la orden");
        }
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
