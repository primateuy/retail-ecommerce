/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

const CONTROL_BUTTON_PERMISSION_MAP = {
    RefundButton: "pos_allow_refund_button",
    SetPricelistButton: "pos_allow_pricelist_button",
    OrderlineCustomerNoteButton: "pos_allow_customer_note_button",
    DiscountButton: "pos_allow_discount_button",
    RewardButton: "pos_allow_reward_button",
    eWalletButton: "pos_allow_ewallet_button",
    PromoCodeButton: "pos_allow_promo_code_button",
    ResetProgramsButton: "pos_allow_reset_programs_button",
    CreateOrderButton: "pos_allow_quotation_button",
    SaleOrderButton: "pos_allow_quotation_button",
    CreateSalesOrderButton: "pos_allow_quotation_button",
    SeePosOrderButton: "pos_allow_quotation_button",
    SalespersonButton: "pos_allow_salesperson_button",
    ZReportButton: "pos_allow_z_report_button",
};

const CONTROL_BUTTON_TEMPLATE_PERMISSION_MAP = {
    "point_of_sale.RefundButton": "pos_allow_refund_button",
    "point_of_sale.SetPricelistButton": "pos_allow_pricelist_button",
    "point_of_sale.OrderlineCustomerNoteButton": "pos_allow_customer_note_button",
    "pos_discount.DiscountButton": "pos_allow_discount_button",
    "pos_loyalty.RewardButton": "pos_allow_reward_button",
    "point_of_sale.eWalletButton": "pos_allow_ewallet_button",
    "pos_loyalty.PromoCodeButton": "pos_allow_promo_code_button",
    "pos_loyalty.ResetProgramsButton": "pos_allow_reset_programs_button",
    "pos_order_to_sale_order.CreateOrderButton": "pos_allow_quotation_button",
    "pos_orders_all.SeePosOrderButton": "pos_allow_quotation_button",
    "pos_orders_all.CreateSalesOrderButton": "pos_allow_quotation_button",
    "pos_orders_all.SaleOrderButton": "pos_allow_quotation_button",
    "pw_pos_salesperson.SalespersonButton": "pos_allow_salesperson_button",
    "adevx_pos_z_report.ZReportButton": "pos_allow_z_report_button",
};

const controlButtonsDescriptor =
    Object.getOwnPropertyDescriptor(ProductScreen.prototype, "controlButtons") ||
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(ProductScreen.prototype), "controlButtons");
const originalControlButtonsGetter = controlButtonsDescriptor && controlButtonsDescriptor.get;
const originalGetNumpadButtons = ProductScreen.prototype.getNumpadButtons;

patch(ProductScreen.prototype, {
    get controlButtons() {
        // Obtener botones base ya ordenados
        const buttons = originalControlButtonsGetter ? originalControlButtonsGetter.call(this) : [];

        // Filtrar segun permisos del cajero
        return buttons.filter((button) => {
            const template = button.component?.template;
            return this._isControlButtonAllowed(button.name, template);
        });
    },

    _isControlButtonAllowed(buttonName, buttonTemplate) {
        // Permitir todo cuando POS HR no esta activo
        if (!this.pos.config.module_pos_hr) {
            return true;
        }

        // Permitir todo si no hay cajero definido
        const cashier = this.pos.get_cashier?.();
        if (!cashier || !cashier.id) {
            return true;
        }

        // Validar permiso por template o nombre del componente
        const fieldName =
            CONTROL_BUTTON_TEMPLATE_PERMISSION_MAP[buttonTemplate] ||
            CONTROL_BUTTON_PERMISSION_MAP[buttonName];
        if (!fieldName) {
            return true;
        }
        return Boolean(cashier[fieldName]);
    },

    /**
     * Devuelve los botones del Numpad aplicando permisos del cajero.
     * Igual que pos_access_right_hr: no se eliminan botones (evita romper el layout),
     * sino que se marca disabled en los que el empleado no tiene permiso.
     */
    getNumpadButtons() {
        const buttons = originalGetNumpadButtons.call(this);

        if (!this.pos.config.module_pos_hr) {
            return buttons;
        }

        const cashier = this.pos.get_cashier?.();
        if (!cashier || !cashier.id) {
            return buttons;
        }

        // Aplicar permisos como en pos_access_right_hr: mantener todos los botones
        // y usar disabled en lugar de filtrar, para no romper la vista del Numpad.
        return buttons.map((button) => {
            let disabled = button.disabled;
            if (button.value === "discount") {
                disabled = disabled || !cashier.pos_allow_numpad_discount;
            } else if (button.value === "price") {
                disabled = disabled || !cashier.pos_allow_numpad_price;
            }
            return { ...button, disabled };
        });
    },

    /**
     * Bloquea el cambio a modo descuento o precio por teclado/atajo cuando el cajero
     * no tiene permiso (mismo criterio que pos_access_right_hr).
     */
    async updateSelectedOrderline({ buffer, key }) {
        const cashier = this.pos?.get_cashier?.();
        if (this.pos.config.module_pos_hr && cashier?.id) {
            if (key === "discount" && !cashier.pos_allow_numpad_discount) {
                return;
            }
            if (key === "price" && !cashier.pos_allow_numpad_price) {
                return;
            }
        }
        return super.updateSelectedOrderline(...arguments);
    },
});
