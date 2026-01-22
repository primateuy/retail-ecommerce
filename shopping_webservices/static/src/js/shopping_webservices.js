/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AccountMoveWidget extends Component {
    static template = "shopping_webservices.AccountMoveWidget";
    static props = ["*"]

    setup() {
        this.state = useState({
            multiplesPagos: false,
            journalData: null,
            paymentMethods: [],
            payments: [],
            inputType: 'percentage', // 'amount' o 'percentage'
            totalAmount: 0,
            remainingAmount: 0,
            remainingPercentage: 100
        });

        this.orm = useService("orm");
        this.loadJournalData();
    }

    async loadJournalData() {
        const journal_id = this.props.record.data.journal_id?.[0];
        const totalAmount = this.props.record.data.amount_total || 0;
        this.state.totalAmount = totalAmount;
        this.state.remainingAmount = totalAmount;
        
        if (journal_id) {
            try {
                const datos = await this.orm.searchRead(
                    "account.journal", 
                    [["id", "=", journal_id]],
                    ["name", "type", "code", "company_id", "shopping_payment_method_ids"]
                );

                if (datos.length > 0) {
                    this.state.journalData = datos[0];
                    const paymentMethodIds = datos[0].shopping_payment_method_ids;
                    
                    // Si hay más de un método de pago
                    if (paymentMethodIds && paymentMethodIds.length > 1) {
                        this.state.multiplesPagos = true;
                        await this.loadPaymentMethods(paymentMethodIds);
                    }
                }
            } catch (error) {
                console.error("Error cargando journal:", error);
            }
        }
    }

    async loadPaymentMethods(methodIds) {
        try {
            const methods = await this.orm.read(
                "shopping.payment.method",
                methodIds,
                ["name", "shopping_code", "payment_code"]
            );
            
            this.state.paymentMethods = methods;
            
            // Cargar distribución guardada si existe
            const savedDistribution = this.props.record.data.payment_distribution;
            
            if (savedDistribution) {
                try {
                    const distributionData = JSON.parse(savedDistribution);
                    this.state.payments = methods.map(method => {
                        const saved = distributionData.find(d => d.payment_method_id === method.id);
                        return {
                            id: method.id,
                            name: method.name,
                            shopping_code: method.shopping_code,
                            payment_code: method.payment_code,
                            amount: saved?.amount || 0,
                            percentage: saved?.percentage || 0
                        };
                    });
                    this.calculateRemaining();
                } catch (e) {
                    console.error("Error parsing saved distribution:", e);
                    this.initializePayments(methods);
                }
            } else {
                this.initializePayments(methods);
            }
        } catch (error) {
            console.error("Error cargando métodos de pago:", error);
        }
    }

    initializePayments(methods) {
        this.state.payments = methods.map(method => ({
            id: method.id,
            name: method.name,
            shopping_code: method.shopping_code,
            payment_code: method.payment_code,
            amount: 0,
            percentage: 0
        }));
    }

    onInputTypeChange(ev) {
        this.state.inputType = ev.target.value;
        this.calculateRemaining();
    }

    onPaymentChange(paymentId, value) {
        const payment = this.state.payments.find(p => p.id === paymentId);
        
        if (this.state.inputType === 'amount') {
            payment.amount = parseFloat(value) || 0;
            payment.percentage = this.state.totalAmount > 0 
                ? (payment.amount / this.state.totalAmount) * 100 
                : 0;
        } else {
            payment.percentage = parseFloat(value) || 0;
            payment.amount = (payment.percentage / 100) * this.state.totalAmount;
        }
        
        this.calculateRemaining();
        this.savePaymentDistribution();
    }

    savePaymentDistribution() {
        // Preparar datos para guardar
        const distributionData = this.state.payments.map(p => ({
            payment_method_id: p.id,
            payment_method_name: p.name,
            shopping_code: p.shopping_code,
            payment_code: p.payment_code,
            amount: p.amount,
            percentage: p.percentage
        }));

        // Guardar en el campo del modelo
        this.props.record.update({
            payment_distribution: JSON.stringify(distributionData)
        });
    }

    calculateRemaining() {
        if (this.state.inputType === 'amount') {
            const totalAssigned = this.state.payments.reduce((sum, p) => sum + p.amount, 0);
            this.state.remainingAmount = this.state.totalAmount - totalAssigned;
            this.state.remainingPercentage = this.state.totalAmount > 0
                ? (this.state.remainingAmount / this.state.totalAmount) * 100
                : 0;
        } else {
            const totalPercentage = this.state.payments.reduce((sum, p) => sum + p.percentage, 0);
            this.state.remainingPercentage = 100 - totalPercentage;
            this.state.remainingAmount = (this.state.remainingPercentage / 100) * this.state.totalAmount;
        }
    }

    getRemainingColor() {
        const remaining = this.state.inputType === 'amount' 
            ? this.state.remainingAmount 
            : this.state.remainingPercentage;
        
        if (Math.abs(remaining) < 0.01) return 'text-success';
        if (remaining < 0) return 'text-danger';
        return 'text-warning';
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('es-UY', {
            style: 'currency',
            currency: 'UYU'
        }).format(amount);
    }
}

registry.category("view_widgets").add("account_move_widget", {
    component: AccountMoveWidget,
});