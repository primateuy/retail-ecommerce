import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { printPdf } from "@l10n_uy_pos_cfe_print/app/utils/print_pdf";

patch(PosStore.prototype, {
    /**
     * URL del PDF del CFE de Uruware de la orden, si la caja usa «Descargar factura FE».
     *
     * @param {Object} order orden del PdV.
     * @returns {Promise<string|false>} false si la caja no lo usa, la orden no está
     *     facturada, el CFE no fue emitido o Uruware no respondió.
     */
    async getCfePdfUrl(order) {
        const accountMoveId = order?.raw?.account_move;
        if (!this.config.download_invoice_fe || !accountMoveId) {
            return false;
        }
        try {
            return await this.data.call("account.move", "get_pos_cfe_pdf_url", [accountMoveId]);
        } catch (error) {
            // Sin el PDF de Uruware el PdV sigue con el recibo de Odoo.
            console.warn("l10n_uy_pos_cfe_print: no se pudo obtener el PDF del CFE", error);
            return false;
        }
    },

    async printReceipt(options = {}) {
        const { basic = false, order = this.getOrder() } = options;
        if (!basic) {
            const url = await this.getCfePdfUrl(order);
            if (url) {
                await printPdf(url);
                return true;
            }
        }
        return super.printReceipt(...arguments);
    },
});
