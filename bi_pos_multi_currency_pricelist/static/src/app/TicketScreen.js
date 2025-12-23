/** @odoo-module */

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype, {

    setup() {
        super.setup();
    },
    // getTotal(order) { var self = this; var amount =
    // order.get_total_with_tax(); let all_curr = this.pos.currencies

    //     // all_curr.forEach(function (curr) {
    //     //     console.log("____order.pricelist",order)
            

    //     //     if (curr.id == order.pricelist.currency_id[0]){
    //     //         self.pos.currency = curr
    //     //     }
            
    //     // }); order = this.pos.selectedOrder var currency_convert =
    //        order.pricelist.currency_convert;
    //     // var currency_convert = this.pos.currency.currency_convert
    //     // console.log('55555555',currency) if(currency_convert){ amount =
    //        amount * currency_convert; } return
    //        self.env.utils.formatCurrency(amount);
        
    // },

    onClickOrder(clickedOrder) {
        clickedOrder.pricelist = this.pos.selectedOrder.pricelist
        this._state.ui.selectedOrder = clickedOrder;
        this._state.ui.selectedOrder.pricelist = clickedOrder.pricelist;
        this.numberBuffer.reset();
        if ((!clickedOrder || clickedOrder.locked) && !this.getSelectedOrderlineId()) {
            // Automatically select the first orderline of the selected order.
            const firstLine = this._state.ui.selectedOrder.get_orderlines()[0];
            if (firstLine) {
                this._state.ui.selectedOrderlineIds[clickedOrder.backendId] = firstLine.id;
            }
        }
    },

    _getToRefundDetail(orderline) {
        var self = this;
        const { toRefundLines } = this.pos;
        if (orderline.id in toRefundLines) {
            return toRefundLines[orderline.id];
        }
        const partner = orderline.order.get_partner();
        const orderPartnerId = partner ? partner.id : false;

        let all_curr = this.pos.currencies

        all_curr.forEach(function (curr) {
            if (curr.id == orderline.order.pricelist.currency_id[0]){
                self.pos.currency = curr
            }
           
        });

        var currency = this.pos.currency;

        var converted_price = currency ? orderline.price * currency.currency_convert : orderline.price;
        
        const newToRefundDetail = {
            qty: 0,
            orderline: {
                id: orderline.id,
                productId: orderline.product.id,
                price: converted_price,
                qty: orderline.quantity,
                refundedQty: orderline.refunded_qty,
                orderUid: orderline.order.uid,
                orderBackendId: orderline.order.backendId,
                orderPartnerId,
                tax_ids: orderline.get_taxes().map((tax) => tax.id),
                discount: orderline.discount,
                pack_lot_lines: orderline.pack_lot_lines
                    ? orderline.pack_lot_lines.map((lot) => {
                          return { lot_name: lot.lot_name };
                      })
                    : false,
            },
            destinationOrderUid: false,
        };
        toRefundLines[orderline.id] = newToRefundDetail;
        return newToRefundDetail;
    }
});
