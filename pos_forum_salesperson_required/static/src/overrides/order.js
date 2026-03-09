/** @odoo-module */

import { Order, Orderline } from "@point_of_sale/app/store/models";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(Order.prototype, {
    setup(_defaultObj, options) {
        // Ejecutar la inicialización base de la orden
        super.setup(...arguments);

        // Inicializar el vendedor de la orden si aún no existe
        this.order_salesperson = this.order_salesperson || null;
    },

    init_from_JSON(json) {
        // Ejecutar la carga estándar desde JSON
        super.init_from_JSON(...arguments);

        // Asignar vendedor de la orden desde el backend si viene informado
        if (json.order_salesperson_id) {
            const employee = this._getEmployeeById(json.order_salesperson_id);
            if (employee) {
                this.set_order_salesperson(employee);
            }
        }
    },

    export_as_JSON() {
        // Exportar datos base de la orden
        const json = super.export_as_JSON(...arguments);

        // Agregar el vendedor de la orden para el backend
        json.order_salesperson_id = this.order_salesperson ? this.order_salesperson.id : false;

        // Retornar el JSON completo
        return json;
    },

    _getEmployeeById(employeeId) {
        // Buscar el empleado en la lista cargada en POS
        return (this.pos.employees || []).find((emp) => emp.id === employeeId) || null;
    },

    set_order_salesperson(employee) {
        // Guardar el empleado como vendedor de la orden
        this.order_salesperson = employee || null;
    },

    get_order_salesperson() {
        // Retornar el vendedor de la orden actual
        return this.order_salesperson || null;
    },

    apply_order_salesperson_to_lines() {
        // Salir si no hay vendedor de la orden definido
        if (!this.order_salesperson) {
            return;
        }

        // Asignar vendedor a las líneas sin vendedor
        for (const line of this.get_orderlines()) {
            if (line.get_line_emp && !line.get_line_emp()) {
                line.set_line_emp(this.order_salesperson);
            }
        }
    },

    has_line_without_salesperson() {
        // Verificar si existe alguna línea sin vendedor
        return this.get_orderlines().some((line) => line.get_line_emp && !line.get_line_emp());
    },

    /**
     * Exige vendedor de la orden y en todas las líneas antes de permitir entrar
     * a la pantalla de pago. Así se evita llegar a Validar con métodos
     * irreversibles (tarjeta, Mercado Pago, etc.) sin poder volver a asignar vendedor.
     */
    async pay() {
        if (!this.canPay()) {
            return;
        }

        const orderSalesperson = this.get_order_salesperson?.();
        if (!orderSalesperson) {
            await this.env.services.popup.add(ErrorPopup, {
                title: _t("Missing Salesperson"),
                body: _t("Please select a salesperson for the order before paying."),
            });
            return;
        }

        this.apply_order_salesperson_to_lines?.();
        if (this.has_line_without_salesperson?.()) {
            await this.env.services.popup.add(ErrorPopup, {
                title: _t("Missing Salesperson"),
                body: _t("All order lines must have a salesperson before paying."),
            });
            return;
        }

        return await super.pay(...arguments);
    },

    async add_product(product, options) {
        // Ejecutar la lógica estándar de agregar producto
        const line = await super.add_product(...arguments);

        // Heredar vendedor de la orden si la línea aún no tiene vendedor
        if (line && this.get_order_salesperson && this.get_order_salesperson()) {
            if (line.get_line_emp && !line.get_line_emp()) {
                line.set_line_emp(this.get_order_salesperson());
            }
        }

        // Retornar la línea creada
        return line;
    },
});

patch(Orderline.prototype, {
    set_line_emp(user) {
        // Ejecutar la asignación estándar en la línea
        super.set_line_emp(...arguments);

        // Si la orden no tiene vendedor, heredar desde la línea
        if (this.order && this.order.get_order_salesperson && !this.order.get_order_salesperson()) {
            this.order.set_order_salesperson(user);
        }
    },
});
