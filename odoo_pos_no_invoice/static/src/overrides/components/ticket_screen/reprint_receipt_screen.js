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
     * Datos del ticket que se reimprime: los que trajo reprint_receipt_button del servidor
     * (cliente, IVA, CFE, puntos), si son de esta orden. Si no, los de la caja.
     *
     * Devuelve el mismo objeto en cada render: la plantilla lo pasa como `data` a OrderReceipt.
     */
    get datosDelRecibo() {
        const guardados = this.pos._reprintDatos;
        const base = this.props.order.export_for_printing();
        if (guardados?.data && guardados.ticket === base.name) {
            return guardados.data;
        }
        return base;
    },

    /**
     * Extiende tryReprint para incluir CFE data pre-obtenida por reprint_receipt_button.
     */
    tryReprint() {
        const guardados = this.pos._reprintDatos;
        if (guardados?.data && guardados.ticket === this.props.order.export_for_printing().name) {
            // El mismo ticket que se ve en pantalla (Forum, 2026-11-20).
            this.printer.print(
                OrderReceipt,
                { data: guardados.data, formatCurrency: this.env.utils.formatCurrency },
                { webPrintFallback: true }
            );
            return;
        }
        const cfeData = this.pos._reprintCfeData || {};
        // Igual que cfe_data: el barcode ya lo trajo reprint_receipt_button desde el
        // servidor. Sin esto el recibo cae al fallback por URL y sale el PNG
        // estirado que no lee la pistola.
        const barcode = this.pos._reprintBarcode || false;
        const baseData = this.props.order.export_for_printing();
        // Puntos de la venta reimpresa, que trajo reprint_receipt_button (Forum, 2026-11-20).
        const reprintLoyalty = this.pos._reprintLoyalty || {};
        this.printer.print(
            OrderReceipt,
            {
                data: { ...baseData, cfe_data: cfeData, barcode, reprint_loyalty: reprintLoyalty },
                formatCurrency: this.env.utils.formatCurrency,
            },
            { webPrintFallback: true }
        );
    },
});
