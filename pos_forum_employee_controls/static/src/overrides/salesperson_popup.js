/** @odoo-module */

import { SalespersonPopup } from "@pw_pos_salesperson_emp/input_popups/salesperson_popup";
import { patch } from "@web/core/utils/patch";

patch(SalespersonPopup.prototype, {
    setup() {
        // Ejecutar configuración base del popup
        super.setup(...arguments);

        // Normalizar lista: propagar identification_id desde el empleado al item de lista
        if (Array.isArray(this.props.list)) {
            for (const entry of this.props.list) {
                if (
                    entry &&
                    entry.item &&
                    entry.item.identification_id &&
                    !entry.identification_id
                ) {
                    entry.identification_id = entry.item.identification_id;
                }
            }
        }
    },

    async onChangeSalesperson(empName) {
        // Buscar por label exacto
        let selectedEmp = this.props.list.find((item) => item.label === empName);

        // Si no se encuentra, intentar por numero de documento
        if (!selectedEmp) {
            const normalized = (empName || "").trim();
            selectedEmp = this.props.list.find(
                (item) => item.identification_id && item.identification_id === normalized
            );
        }

        // Si se encontro, guardar seleccion
        if (selectedEmp) {
            this.selectedEmp = selectedEmp;
        }
    },
});
