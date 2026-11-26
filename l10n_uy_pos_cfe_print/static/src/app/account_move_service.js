import { AccountMoveService } from "@account/services/account_move_service";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { patch } from "@web/core/utils/patch";

// Tanto la descarga automática al validar la venta como el botón de factura de la lista
// de pedidos pasan por downloadPdf; el servidor decide si devuelve el CFE de Uruware o
// el PDF estándar de Odoo.
patch(AccountMoveService.prototype, {
    async downloadPdf(accountMoveId, target = "download") {
        // Sin «Descargar factura FE» en la caja, la factura sale como en Odoo estándar.
        if (!this.env.services.pos?.config?.download_invoice_fe) {
            return super.downloadPdf(accountMoveId, target);
        }
        const downloadAction = await this.orm.call(
            "account.move",
            "action_pos_download_cfe_pdf",
            [accountMoveId, target]
        );
        if (!downloadAction) {
            // Uruware no devolvió el PDF: se avisa y la venta sigue; no se cae a la
            // descarga estándar porque con FE activa también llama a Uruware y falla.
            this.env.services.notification.add(
                _t(
                    "No se pudo obtener el PDF de la factura desde Uruware. La venta quedó facturada; podés reimprimirla desde Órdenes."
                ),
                { type: "warning", sticky: true }
            );
            return;
        }
        if (target === "download" && downloadAction.url) {
            // doAction abre la URL con window.open, y tras la espera a Uruware el navegador
            // ya no lo asocia al clic del cajero y bloquea la ventana emergente.
            await download({ url: downloadAction.url, data: {} });
            return;
        }
        await this.action.doAction(downloadAction);
    },
});
