/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async _processData(loadedData) {
        // Ejecutar la carga base de datos del POS
        await super._processData(...arguments);

        // Guardar los tipos de identificacion para el editor de clientes
        this.identification_types = loadedData["l10n_latam.identification.type"] || [];

        // Crear indice rapido por id para consultas en el frontend
        this.identification_type_by_id = {};
        for (const item of this.identification_types) {
            this.identification_type_by_id[item.id] = item;
        }

        // Guardar bandera de disponibilidad de partner_firstname
        this.partner_firstname_enabled = Boolean(loadedData.partner_firstname_enabled);
    },
});
