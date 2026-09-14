/** @odoo-module **/
/*
 * pos_cfc_contingencia — el folio viaja con la orden.
 *
 * Guardarlo en la orden y no en el componente de pantalla resuelve dos cosas:
 *
 *   - Llega al backend por el camino normal del POS (`export_as_JSON`), sin
 *     depender del RPC que `pos_reference_for_payment` dispara después de
 *     finalizar la validación.
 *   - Muere con la orden. El estado del PaymentScreen sobrevive entre ventas,
 *     así que un folio guardado ahí podía arrastrarse a la orden siguiente y
 *     repetir el número del talonario.
 *
 * También se restaura desde el JSON para que una orden recuperada de
 * localStorage (cierre del navegador, modo offline) no pierda el folio.
 */
import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.cfc_folio = this.cfc_folio || "";
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.cfc_folio = json.cfc_folio || "";
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.cfc_folio = this.cfc_folio || "";
        return json;
    },
});
