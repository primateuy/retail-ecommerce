/** @odoo-module */

/**
 * Popup de captura de datos para transacciones de pago manuales.
 *
 * Renderiza campos según la configuración JSON del proveedor (ticket, lote,
 * sello many2one a marcas, etc.) sin reutilizar el formulario de cheques.
 */

import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";

export class ManualPaymentPopup extends AbstractAwaitablePopup {
    static template = "pos_forum_manual_payment.ManualPaymentPopup";

    static defaultProps = {
        confirmText: _t("Aplicar"),
        cancelText: _t("Cancelar"),
        title: _t("Datos de transacción manual"),
        fieldConfigJson: "[]",
        partnerName: "",
    };

    /**
     * Prepara estado con valores iniciales según configuración y partner.
     */
    setup() {
        super.setup(...arguments);
        let fields = [];
        try {
            fields = JSON.parse(this.props.fieldConfigJson || "[]");
        } catch (error) {
            fields = [];
        }
        const values = {};
        for (const field of fields) {
            if (field.field_type === "char") {
                if (field.special_default === "partner_name") {
                    values[field.code] = this.props.partnerName || "";
                } else {
                    values[field.code] = field.default || "";
                }
            } else if (field.field_type === "many2one") {
                values[field.code] = field.default_id || false;
            }
        }
        this.state = useState({ fields, values });
    }

    /**
     * Actualiza un valor de campo de texto en el estado.
     */
    updateCharValue(code, event) {
        this.state.values[code] = event.target.value;
    }

    /**
     * Actualiza un valor many2one (id) en el estado.
     */
    updateMany2oneValue(code, event) {
        const value = event.target.value;
        this.state.values[code] = value ? parseInt(value, 10) : false;
    }

    /**
     * Valor string para el atributo value del select (OWL no admite String() en XML).
     */
    getSelectStringValue(code) {
        const raw = this.state.values[code];
        if (raw === undefined || raw === null || raw === false) {
            return "";
        }
        return `${raw}`;
    }

    /**
     * Indica si la opción del select debe mostrarse seleccionada.
     */
    isOptionSelected(code, optId) {
        const current = this.state.values[code];
        if (current === undefined || current === null || current === false) {
            return false;
        }
        return parseInt(`${current}`, 10) === parseInt(`${optId}`, 10);
    }

    /**
     * Valida campos obligatorios y cierra con payload o sin cerrar si falla.
     */
    async confirm() {
        const missing = [];
        for (const field of this.state.fields) {
            if (!field.required) {
                continue;
            }
            const value = this.state.values[field.code];
            const empty =
                value === undefined ||
                value === null ||
                value === false ||
                (typeof value === "string" && value.trim() === "");
            if (empty) {
                missing.push(field.label);
            }
        }
        if (missing.length) {
            alert(_t("Complete los campos obligatorios: ") + missing.join(", "));
            return;
        }
        this.props.close({
            confirmed: true,
            payload: { values: { ...this.state.values } },
        });
    }

    /**
     * Cierra sin confirmar.
     */
    cancel() {
        this.props.close({ confirmed: false, payload: null });
    }
}
