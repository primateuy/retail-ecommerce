/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { PaymentMercadoPago } from "@pos_mercado_pago/app/payment_mercado_pago";
import { usePos } from "@point_of_sale/app/store/pos_hook";
// import { MercadoPagoPopup } from "@pos_mercadopago/components/popup_qr/popup_qr";
// import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
// import { omit } from "@web/core/utils/objects";
// import { useService } from "@web/core/utils/hooks";

export class PaymentMercadoPagoQR extends PaymentMercadoPago {
    async setup(){
        super.setup(...arguments);
        // Asignamos la caja
        this.set_store_till();
    }

    // Metodo para establecer la caja
    async set_store_till() {
        // Obtenemos informacion de la caja
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
        
        if (this.pos.qr_type == "dynamic" && orderFrontend.paymentlines.length > 1) {
            return this._showMsg(
                "Cuando la modalidad del QR de Mercado Pago es dinamico, la orden debe ser pagada completamente por este metodo de pago",
                "| Validacion de Antes de Crear la Orden"
            )
        }


        // Variable para saber si mercado pago esta como metodo de pago a cancelar
        let paymentMethodMP = false;
        // Recorremos los metodos de pagos seleccionados para revisar si esta mercadopago
        for (let i = 0; i < orderFrontend.paymentlines.length; i++) {
            if (orderFrontend.paymentlines[i].payment_method.id == this.payment_method.id) {
                paymentMethodMP = true;
            }
        }

        // Validamos si mercadopago esta como metodo de pago
        if (paymentMethodMP) {
            try {
                // Lista de items en la orden
                const posOrders = [];
                const paymentLines = this.get_paymentlines(orderFrontend.paymentlines)
                
                for (let i = 0; i < orderFrontend.orderlines.length; i++) {
                    posOrders.push({
                        "id": orderFrontend.orderlines[i].id,
                        "title": orderFrontend.orderlines[i].full_product_name,
                        "currency_id": "UYU",
                        "unit_price": orderFrontend.orderlines[i].price,
                        "quantity": orderFrontend.orderlines[i].quantity,
                        "description": orderFrontend.orderlines[i].product?.description || orderFrontend.orderlines[i].full_product_name,
                        "product_id": orderFrontend.orderlines[i].product.id,
                        "tax_ids": orderFrontend.orderlines[i].tax_ids || orderFrontend.orderlines[i].product.taxes_id,
                        "tax_ids_after_fiscal_position": orderFrontend.orderlines[i].tax_ids || orderFrontend.orderlines[i].product.taxes_id,
                        "standard_price": orderFrontend.orderlines[i].product.standard_price,
                    })
                }

                // Creamos la orden por endpoint
                const order = await this.pos.orm.rpc(
                    "/pos/create-order",
                    {
                        store_till_id: this.pos.store_till.id,
                        items: posOrders,
                        session_id: this.pos.pos_session.id,
                        user_id: this.pos.pos_session.user_id[0],
                        partner_id: orderFrontend.partner?.id || false,
                        cashier_id: orderFrontend.order_salesperson?.id || false,
                        amount_paid: 0,
                        company_id: this.pos.config.company_id[0],
                        qr_type: this.pos.qr_type,
                        paymentLines: paymentLines
                    }
                );
                this.orderToPaid = JSON.parse(order);

                const self = this;
                const position = document.querySelector(".right-content");

                const prevImg = document.querySelector(".right-content img#qr_code_pos");
                const prevAcept = document.querySelector(".right-content button#validate-btn");
                const prevCancel = document.querySelector(".right-content button#delete-order-btn");
                if (prevImg) position.removeChild(prevImg);
                if (prevAcept) position.removeChild(prevAcept);
                if (prevCancel) position.removeChild(prevCancel);

                const img = document.createElement("img");
                img.className = "m-5 d-flex";
                img.id = "qr_code_pos";
                img.width = "200";
                img.height = "200";

                const buttonAcept = document.createElement("button");
                buttonAcept.className = "btn btn-primary mx-3 py-2 px-3";
                buttonAcept.textContent = "Comprobar pago";
                buttonAcept.id = "validate-btn";

                const buttonCancel = document.createElement("button");
                buttonCancel.className = "btn btn-danger mx-3 py-2 px-3";
                buttonCancel.textContent = "Eliminar Orden";
                buttonCancel.id = "delete-order-btn";

                position.appendChild(img);
                position.appendChild(buttonAcept);
                position.appendChild(buttonCancel);

                img.src = this.pos.qr_type == 'static' ? this.pos.store_till.qr_url : this.orderToPaid.data.qr_data;

                buttonAcept.onclick = async (e) => {
                    e.target.disabled = true;
                    buttonCancel.disabled = true;
                    try {
                        const result = await self.env.services.orm.searchRead(
                            "pos.order",
                            [["id", "=", self.orderToPaid["pos.order"]["id"]]]
                        );

                        if (result[0].state == "draft") {
                            return self._showMsg(
                                "La orden aun sigue sin recibir el pago",
                                "| Comprobacion del Pago"
                            );
                        }

                        const frontendOrder = self.pos.get_order();
                        frontendOrder.finalized = true;
                        self.pos.db.remove_unpaid_order(frontendOrder);

                        self.pos.showScreen("ReceiptScreen");
                    } catch (err) {
                        console.error("Error al comprobar pago", err);
                        self._showMsg("Hubo un error al comprobar el pago", "| Error");
                    } finally {
                        e.target.disabled = false;
                        buttonCancel.disabled = false;
                    }
                };

                buttonCancel.onclick = async (e) => {
                    e.target.disabled = true;
                    buttonAcept.disabled = true;
                    try {
                        const result = await self.pos.orm.rpc(
                            "/pos/delete-order",
                            {
                                external_id: self.pos.store_till.external_id,
                                user_id: self.pos.store_till.user_id_mp,
                                session_id: self.pos.pos_session.id,
                                order_id: self.orderToPaid["pos.order"]["id"]
                            }
                        );

                        if (JSON.parse(result).error == false) {
                            position.removeChild(buttonCancel);
                            position.removeChild(buttonAcept);
                            position.removeChild(img);
                        } else {
                            e.target.disabled = false;
                            buttonAcept.disabled = false;
                        }
                    } catch (err) {
                        console.error("Error al eliminar orden", err);
                        self._showMsg("Hubo un error al eliminar la orden", "| Error");
                        e.target.disabled = false;
                        buttonAcept.disabled = false;
                    }
                };

            } catch (error) {
                console.error("Hubo un error al buscar la configuracion");
                console.log(error);
                return this._showMsg(
                    "Hubo un error al procesar la orden",
                    "| Error al procesar la orden"
                )
            }
        }
    }

    // Metodo para ordenar los metodos de pago
    get_paymentlines(paymentlines = []) {
        // lista donde guardaremos
        const newPaymentLines = [];

        // Recorremos los metodos de pago
        for (let i = 0; i < paymentlines.length; i++) {
            newPaymentLines.push({
                "amount":paymentlines[i]["amount"],
                "name": paymentlines[i]["name"],
                "payment_method_id": paymentlines[i]["payment_method"]["id"],
                "is_mercado_pago": paymentlines[i]["payment_method"]["id"] == this.payment_method.id,
            });
        }
        return newPaymentLines;
    }
}

register_payment_method("mercado_pago", PaymentMercadoPagoQR);