/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async _processData(loadedData) {
        // Ejecutar la carga estándar de datos del POS
        await super._processData(...arguments);

        // Inicializar el listado de razones cargadas desde el backend
        this.cash_move_reasons = loadedData["pos.move.reason"] || [];

        // Construir un índice rápido por ID para consultas en el frontend
        this.cash_move_reasons_by_id = {};
        for (const reason of this.cash_move_reasons) {
            this.cash_move_reasons_by_id[reason.id] = reason;
        }
    },
});
