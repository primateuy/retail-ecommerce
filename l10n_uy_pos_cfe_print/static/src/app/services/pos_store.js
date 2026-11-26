import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { printPdf } from "@l10n_uy_pos_cfe_print/app/utils/print_pdf";

// Resultado cuando el servidor no respondió: se trata como si Uruware no hubiera devuelto
// el PDF (aviso en la descarga, recibo de Odoo en pantalla e impresión).
const CFE_PDF_UNAVAILABLE = { cfe_emitido: true, url: false };

patch(PosStore.prototype, {
    /**
     * Datos del PDF del CFE de Uruware de una factura (ver account.move.get_pos_cfe_pdf).
     *
     * La descarga, el panel del recibo y la impresión piden lo mismo casi a la vez, así que
     * se comparte una sola llamada por factura. Sólo queda en memoria si hay URL: si el CFE
     * no estaba emitido o Uruware falló, la próxima vez se vuelve a pedir.
     *
     * @param {number} accountMoveId factura de la orden.
     * @returns {Promise<{cfe_emitido: boolean, url: string|false}|null>} null si la caja
     *     no usa «Descargar factura FE» o no hay factura.
     */
    getCfePdf(accountMoveId) {
        if (!this.config.download_invoice_fe || !accountMoveId) {
            return Promise.resolve(null);
        }
        this.cfePdfRequests ??= new Map();
        if (!this.cfePdfRequests.has(accountMoveId)) {
            const request = this.data
                .call("account.move", "get_pos_cfe_pdf", [accountMoveId])
                .catch((error) => {
                    console.warn("l10n_uy_pos_cfe_print: no se pudo obtener el PDF del CFE", error);
                    return CFE_PDF_UNAVAILABLE;
                })
                .then((result) => {
                    if (!result?.url) {
                        this.cfePdfRequests.delete(accountMoveId);
                    }
                    return result || CFE_PDF_UNAVAILABLE;
                });
            this.cfePdfRequests.set(accountMoveId, request);
        }
        return this.cfePdfRequests.get(accountMoveId);
    },

    /**
     * @param {Object} order orden del PdV.
     * @returns {Promise<string|false>} URL en línea del PDF del CFE, o false.
     */
    async getCfePdfUrl(order) {
        return (await this.getCfePdf(order?.raw?.account_move))?.url || false;
    },

    async printReceipt(options = {}) {
        const { basic = false, order = this.getOrder() } = options;
        if (!basic) {
            const url = await this.getCfePdfUrl(order);
            if (url) {
                try {
                    await printPdf(url);
                    return true;
                } catch (error) {
                    // Si el PDF no se pudo cargar para imprimir, sale el recibo de Odoo.
                    console.warn("l10n_uy_pos_cfe_print: no se pudo imprimir el PDF del CFE", error);
                }
            }
        }
        return super.printReceipt(...arguments);
    },
});
