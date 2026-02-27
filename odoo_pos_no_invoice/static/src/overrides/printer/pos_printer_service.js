/** @odoo-module */
/**
 * Override del servicio de impresión para respetar download_invoice.
 *
 * Este parche evita el fallback de impresión web (window.print) cuando la
 * configuración del POS no permite descargar/mostrar PDF.
 */

import { PosPrinterService } from "@point_of_sale/app/printer/pos_printer_service";
import { patch } from "@web/core/utils/patch";

patch(PosPrinterService.prototype, {
    /**
     * Imprime HTML respetando la configuración download_invoice.
     *
     * Si download_invoice es falso, se desactiva el webPrintFallback para evitar
     * el diálogo de impresión/descarga PDF del navegador.
     */
    async printHtml(el, options = {}) {
        // Determinar si se permite el fallback a impresión web.
        const allowWebPrintFallback = !!this.pos?.config?.download_invoice;
        const safeOptions = {
            ...(options || {}),
            webPrintFallback: allowWebPrintFallback && !!options?.webPrintFallback,
        };

        return await super.printHtml(el, safeOptions);
    },
});
