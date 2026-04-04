/** @odoo-module */
/**
 * Encadena la impresión del recibo de venta con el ticket de cambio.
 *
 * Depende de que `odoo_pos_no_invoice` haya parcheado `printReceipt` y de que
 * `odoo_pos_oca` haya añadido `printChangeTicket` al prototipo. Este módulo se
 * carga después de ambos y envuelve `printReceipt` para que un solo clic en
 * "Imprimir" ejecute ambas impresiones cuando el POS tiene reporte de cambio.
 */

import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { patch } from "@web/core/utils/patch";

// Captura la implementación ya parcheada (p. ej. odoo_pos_no_invoice).
const _superPrintReceipt = ReceiptScreen.prototype.printReceipt;

patch(ReceiptScreen.prototype, {
    /**
     * Imprime el recibo de venta y, si está configurado, el ticket de cambio.
     *
     * Se usa el mismo botón "Imprimir" de la pantalla de recibo para no duplicar
     * acciones; el botón independiente de ticket de cambio sigue disponible.
     */
    async printReceipt() {
        // Bloque: impresión del recibo (lógica existente de otros módulos).
        await _superPrintReceipt.call(this);

        // Bloque: ticket de cambio solo si hay reporte en la configuración del POS.
        if (!this.pos.config.change_ticket_report_id) {
            return;
        }

        // Bloque: delegación en el método aportado por odoo_pos_oca.
        await this.printChangeTicket();
    },
});
