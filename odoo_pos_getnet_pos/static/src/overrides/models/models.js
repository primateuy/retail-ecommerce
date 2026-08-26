/** @odoo-module */
// Namespace SIEMPRE @odoo_pos_getnet_pos (lección del bug de Fiserv, cuyo
// import quedó apuntando al namespace del meta-módulo sin assets).
import {register_payment_method} from "@point_of_sale/app/store/pos_store";
import {PaymentGetnet} from "@odoo_pos_getnet_pos/app/payment_getnet";

register_payment_method("getnet", PaymentGetnet);
