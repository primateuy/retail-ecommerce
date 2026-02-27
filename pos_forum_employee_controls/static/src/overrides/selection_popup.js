/** @odoo-module */

import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { patch } from "@web/core/utils/patch";

const originalSetup = SelectionPopup.prototype.setup;

patch(SelectionPopup.prototype, {
    setup() {
        // Ejecutar la configuración base del popup de selección
        originalSetup.call(this, ...arguments);
        // Inicializar término de búsqueda si aún no existe en el estado reactivo
        if (this.state && typeof this.state === "object" && !("searchTerm" in this.state)) {
            this.state.searchTerm = "";
        }
    },

    /**
     * Lista filtrada según el texto de búsqueda.
     * - Busca por label
     * - Por descripción (si existe)
     * - Por identification_id del item o del empleado asociado (item.item.identification_id)
     */
    get filteredList() {
        const search = (this.state?.searchTerm || "").trim().toLowerCase();
        if (!search) {
            return this.props.list || [];
        }

        return (this.props.list || []).filter((item) => {
            const label = (item.label || "").toLowerCase();
            const description = (item.description || "").toLowerCase();
            const docFromItem = (item.identification_id || "").toLowerCase();
            const docFromEmployee =
                (item.item && item.item.identification_id
                    ? String(item.item.identification_id).toLowerCase()
                    : "");

            return (
                label.includes(search) ||
                description.includes(search) ||
                docFromItem.includes(search) ||
                docFromEmployee.includes(search)
            );
        });
    },
});

