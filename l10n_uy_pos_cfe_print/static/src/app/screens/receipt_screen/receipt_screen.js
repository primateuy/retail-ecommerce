import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { onMounted, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        // Mientras llega el PDF de Uruware se muestra el recibo de Odoo.
        this.cfePdf = useState({ url: false });
        onMounted(async () => {
            this.cfePdf.url = await this.pos.getCfePdfUrl(this.currentOrder);
        });
    },
});
