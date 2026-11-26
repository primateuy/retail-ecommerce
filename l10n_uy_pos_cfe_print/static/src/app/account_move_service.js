import { AccountMoveService } from "@account/services/account_move_service";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { patch } from "@web/core/utils/patch";

// Tanto la descarga automática al validar la venta como el botón de factura de la lista
// de pedidos pasan por downloadPdf.
patch(AccountMoveService.prototype, {
    async downloadPdf(accountMoveId, target = "download") {
        const pos = this.env.services.pos;
        // Sin «Descargar factura FE» en la caja, la factura sale como en Odoo estándar.
        if (!pos?.config?.download_invoice_fe) {
            return super.downloadPdf(accountMoveId, target);
        }
        const cfePdf = await pos.getCfePdf(accountMoveId);
        if (!cfePdf.cfe_emitido) {
            return super.downloadPdf(accountMoveId, target);
        }
        if (!cfePdf.url) {
            // Uruware no devolvió el PDF: no se cae a la descarga estándar porque con FE
            // activa también llama a Uruware y termina en error de servidor.
            this.env.services.notification.add(
                _t(
                    "No se pudo obtener el PDF de la factura desde Uruware. La venta quedó facturada; podés reimprimirla desde Órdenes."
                ),
                { type: "warning", sticky: true }
            );
            return;
        }
        if (target === "download") {
            // doAction abriría la URL con window.open y, tras la espera a Uruware, el
            // navegador la bloquea como ventana emergente.
            await download({ url: `${cfePdf.url}&download=true`, data: {} });
            return;
        }
        await this.action.doAction({ type: "ir.actions.act_url", url: cfePdf.url, target });
    },
});
