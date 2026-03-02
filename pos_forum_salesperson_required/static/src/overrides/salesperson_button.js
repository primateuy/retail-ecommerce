/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { SalespersonButton } from "@pw_pos_salesperson_emp/js/SalespersonButton";
import { SalespersonPopup } from "@pw_pos_salesperson_emp/input_popups/salesperson_popup";

patch(SalespersonButton.prototype, {
    async click() {
        // Preparar la lista de empleados disponibles en el POS
        const selectionList = (this.pos.employees || []).map((user) => {
            // Incluir numero de documento en el label para facilitar la busqueda
            const identification = user.identification_id ? ` - ${user.identification_id}` : "";
            return {
                id: user.id,
                label: `${user.name}${identification}`,
                item: user,
                identification_id: user.identification_id,
            };
        });

        // Solicitar selección de vendedor
        const { confirmed, payload: selectedEmp } = await this.popup.add(SalespersonPopup, {
            title: _t("Select Salesperson"),
            list: selectionList,
        });

        // Asignar vendedor a la orden y a todas sus líneas
        if (confirmed && selectedEmp) {
            const order = this.pos.get_order();
            if (order && order.set_order_salesperson) {
                order.set_order_salesperson(selectedEmp);
                for (const line of order.get_orderlines()) {
                    if (line.set_line_emp) {
                        line.set_line_emp(selectedEmp);
                    }
                }
            }
        }
    },
});
