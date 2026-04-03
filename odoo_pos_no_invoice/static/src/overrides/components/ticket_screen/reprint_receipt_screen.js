/** @odoo-module */
/**
 * Override de ReprintReceiptScreen para incluir datos del CFE al imprimir
 * desde la pantalla de reimpresión (botón "Imprimir Recibo" dentro de ReprintReceiptScreen).
 */

import { ReprintReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/reprint_receipt_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";

patch(ReprintReceiptScreen.prototype, {
    /**
     * Extiende tryReprint para incluir CFE data pre-obtenida por reprint_receipt_button.
     */
    tryReprint() {
        const cfeData = this.pos._reprintCfeData || {};
        const baseData = this.props.order.export_for_printing();
        this.printer.print(
            OrderReceipt,
            {
                data: { ...baseData, cfe_data: cfeData },
                formatCurrency: this.env.utils.formatCurrency,
            },
            { webPrintFallback: true }
        );
    },
});
