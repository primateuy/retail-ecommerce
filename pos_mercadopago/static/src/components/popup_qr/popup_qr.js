// static/src/js/MercadoPagoPopup.js
// import { _t } from "@web/core/l10n/translation";
// import { parseFloat } from "@web/views/fields/parsers";
// import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Registries } from "@web/core/registry";

export class MercadoPagoPopup extends Component {
    static template = "pos_mercadopago.MercadoPagoPopup";
    static components = { Dialog };
    setup() {
        super.setup();
        this.notification = useService("notification");
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.state = useState({ message: this.props.message || "¿Confirmar pago con Mercado Pago?" });
    }

    async confirm() {
        // this.props.resolve({ confirmed: true });
        
        this.close();
    }

    cancel() {
        // this.props.resolve({ confirmed: false });
        
        this.close();
    }
}

Registries.Component.add(MercadoPagoPopup);
// registry.category("public_widget").add("pos_mercadopago.MercadoPagoPopup", MercadoPagoPopup);
