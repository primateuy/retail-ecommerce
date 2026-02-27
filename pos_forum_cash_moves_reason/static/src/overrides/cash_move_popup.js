/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { parseFloat } from "@web/views/fields/parsers";
import { CashMovePopup } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_popup";
import { CashMoveReceipt } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_receipt/cash_move_receipt";
import { patch } from "@web/core/utils/patch";

patch(CashMovePopup.prototype, {
    setup() {
        // Ejecutar la inicialización base del popup
        super.setup(...arguments);

        // Agregar el campo de razón seleccionada al estado reactivo
        this.state.move_reason_id = this.state.move_reason_id || 0;
    },

    get cashMoveReasons() {
        // Obtener los IDs de razones configuradas en el POS
        const configReasonIds = this.pos.config.cash_move_reason_ids || [];
        if (!configReasonIds.length) {
            return [];
        }

        // Construir un set para filtrar rápido
        const reasonIdSet = new Set(configReasonIds);

        // Filtrar por tipo de movimiento y razones habilitadas
        return (this.pos.cash_move_reasons || []).filter((reason) => {
            if (!reasonIdSet.has(reason.id)) {
                return false;
            }
            if (this.state.type === "in") {
                return reason.is_income_reason;
            }
            return reason.is_expense_reason;
        });
    },

    _getSelectedMoveReason() {
        // Convertir a entero para evitar inconsistencias de tipo
        const reasonId = parseInt(this.state.move_reason_id, 10);
        if (!reasonId) {
            return null;
        }

        // Buscar la razón en el índice del POS
        return this.pos.cash_move_reasons_by_id?.[reasonId] || null;
    },

    async confirm() {
        // Parsear y validar el monto ingresado
        const amount = parseFloat(this.state.amount);
        const formattedAmount = this.env.utils.formatCurrency(amount);
        if (!amount) {
            this.notification.add(_t("Cash in/out of %s is ignored.", formattedAmount), 3000);
            return this.props.close();
        }

        // Validar selección de razón si hay razones configuradas
        const selectedReason = this._getSelectedMoveReason();
        if (this.cashMoveReasons.length && !selectedReason) {
            this.notification.add(_t("Select a cash move reason before confirming."), 3000);
            return;
        }

        // Preparar datos de movimiento y razón
        const type = this.state.type;
        const translatedType = _t(type);
        const extras = { formattedAmount, translatedType };
        const reasonText = this.state.reason.trim();

        // Construir el texto de razón que se mostrará y guardará en backend
        let backendReason = reasonText;
        if (selectedReason && !backendReason) {
            backendReason = selectedReason.name;
        } else if (selectedReason && backendReason !== selectedReason.name) {
            backendReason = `${selectedReason.name} - ${backendReason}`;
        }

        // Enviar el movimiento al backend con razón seleccionada
        await this.orm.call("pos.session", "try_cash_in_out", [
            [this.pos.pos_session.id],
            type,
            amount,
            backendReason,
            extras,
            selectedReason ? selectedReason.id : false,
        ]);

        // Registrar el movimiento en el log del empleado
        await this.pos.logEmployeeMessage(
            `${_t("Cash")} ${translatedType} - ${_t("Amount")}: ${formattedAmount}`,
            "CASH_DRAWER_ACTION"
        );

        // Imprimir el recibo de movimiento con la razón definida
        await this.printer.print(CashMoveReceipt, {
            reason: backendReason,
            translatedType,
            formattedAmount,
            headerData: this.pos.getReceiptHeaderData(),
            date: new Date().toLocaleString(),
        });

        // Cerrar el popup y notificar resultado
        this.props.close();
        this.notification.add(_t("Successfully made a cash %s of %s.", type, formattedAmount), 3000);
    },
});
