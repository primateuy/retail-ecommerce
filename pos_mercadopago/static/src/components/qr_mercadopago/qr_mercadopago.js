// import { _t } from "@web/core/l10n/translation";
// import { parseFloat } from "@web/views/fields/parsers";
// import { useErrorHandlers, useAsyncLockedMethod } from "@point_of_sale/app/utils/hooks";
// import { registry } from "@web/core/registry";
// import { useService } from "@web/core/utils/hooks";

// import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
// import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
// import { DatePickerPopup } from "@point_of_sale/app/utils/date_picker_popup/date_picker_popup";
// import { ConnectionLostError, RPCError } from "@web/core/network/rpc";

// import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
// import { PaymentScreenStatus } from "@point_of_sale/app/screens/payment_screen/payment_status/payment_status";
// import { usePos } from "@point_of_sale/app/store/pos_hook";
// import { Component, useState, onMounted } from "@odoo/owl";
// import { Numpad, enhancedButtons } from "@point_of_sale/app/generic_components/numpad/numpad";
// import { floatIsZero, roundPrecision } from "@web/core/utils/numbers";
// import { ask } from "@point_of_sale/app/store/make_awaitable_dialog";
// import { handleRPCError } from "@point_of_sale/app/errors/error_handlers";
// import { sprintf } from "@web/core/utils/strings";
// import { serializeDateTime } from "@web/core/l10n/dates";
// import { PaymentMercadoPago } from "@pos_mercado_pago/app/payment_mercado_pago";
// import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines";

// export class QRPaymentMercadoPago extends PaymentMercadoPago {
//     setup() {
//         console.log("En el super");
//         console.log(this);
        
        
//         super.setup(...arguments);
//         console.log("Empezamooos");
//         console.log(this);
//     }
// }