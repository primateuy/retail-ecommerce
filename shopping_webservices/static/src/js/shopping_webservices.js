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
            remainingPercentage: 100,
            hasChanges: false
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
            console.log("📦 Leyendo métodos de pago...");
            const methods = await this.orm.read(
                "shopping.payment.method",
                methodIds,
                ["name", "shopping_code", "payment_code"]
            );
            
            this.state.paymentMethods = methods;
            console.log(`   ✓ ${methods.length} métodos cargados`);
            
            // Cargar distribución guardada si existe
            const savedDistribution = this.props.record.data.payment_distribution;
            
            console.log("🔍 Verificando si existe distribución guardada...");
            console.log("   Raw value:", savedDistribution);
            console.log("   Type:", typeof savedDistribution);
            console.log("   Is empty:", !savedDistribution || savedDistribution.trim() === '');
            
            if (savedDistribution && savedDistribution.trim() !== '') {
                console.log("✅ Distribución encontrada, parseando...");
                try {
                    const distributionData = JSON.parse(savedDistribution);
                    console.log("   Cantidad de métodos en JSON:", distributionData.length);
                    console.log("   Datos completos:", distributionData);
                    
                    this.state.payments = methods.map(method => {
                        const saved = distributionData.find(d => d.payment_method_id === method.id);
                        
                        if (saved) {
                            const amount = parseFloat(saved.amount) || 0;
                            const percentage = parseFloat(saved.percentage) || 0;
                            
                            console.log(`   → ${method.name}: $${amount.toFixed(2)} (${percentage.toFixed(2)}%)`);
                            
                            return {
                                id: method.id,
                                name: method.name,
                                shopping_code: method.shopping_code,
                                payment_code: method.payment_code,
                                amount: amount,
                                percentage: percentage
                            };
                        } else {
                            console.log(`   → ${method.name}: Sin datos guardados`);
                            return {
                                id: method.id,
                                name: method.name,
                                shopping_code: method.shopping_code,
                                payment_code: method.payment_code,
                                amount: 0,
                                percentage: 0
                            };
                        }
                    });
                    
                    // Recalcular después de cargar
                    this.calculateRemaining();
                    this.state.hasChanges = false;
                    console.log("✓ Distribución cargada y validada correctamente");
                    
                } catch (e) {
                    console.error("❌ Error parseando JSON:", e);
                    console.error("   JSON inválido:", savedDistribution);
                    this.initializePayments(methods);
                }
            } else {
                console.log("ℹ No hay distribución guardada, inicializando nueva");
                this.initializePayments(methods);
            }
        } catch (error) {
            console.error("❌ Error cargando métodos de pago:", error);
        }
    }

    initializePayments(methods) {
        console.log("🆕 Inicializando distribución nueva (sin datos guardados)");
        this.state.payments = methods.map(method => ({
            id: method.id,
            name: method.name,
            shopping_code: method.shopping_code,
            payment_code: method.payment_code,
            amount: 0,
            percentage: 0
        }));
        console.log(`   ✓ ${this.state.payments.length} métodos inicializados con 0`);
        this.state.hasChanges = false;
    }

    verifyStoredData() {
        const stored = this.props.record.data.payment_distribution;
        console.log("\n🔎 === VERIFICACIÓN DE DATOS GUARDADOS ===");
        console.log("Valor almacenado en BD:", stored);
        console.log("Largo del string:", stored ? stored.length : 0);
        
        if (stored) {
            try {
                const parsed = JSON.parse(stored);
                console.log("✓ JSON válido");
                console.log("Cantidad de métodos:", parsed.length);
                console.log("Detalle:", JSON.stringify(parsed, null, 2));
            } catch (e) {
                console.error("❌ JSON inválido:", e.message);
            }
        } else {
            console.log("⚠ Campo VACIO");
        }
        console.log("========================================\n");
    }

    onInputTypeChange(ev) {
        this.state.inputType = ev.target.value;
        this.calculateRemaining();
    }

    onPaymentChange(paymentId, value) {
        const payment = this.state.payments.find(p => p.id === paymentId);
        
        if (!payment) {
            console.error("Payment not found:", paymentId);
            return;
        }
        
        const numValue = parseFloat(value) || 0;
        
        console.log(`Cambio en ${payment.name}: ${value} (tipo: ${this.state.inputType})`);
        
        if (this.state.inputType === 'amount') {
            payment.amount = numValue;
            payment.percentage = this.state.totalAmount > 0 
                ? (payment.amount / this.state.totalAmount) * 100 
                : 0;
        } else {
            payment.percentage = numValue;
            payment.amount = (payment.percentage / 100) * this.state.totalAmount;
        }
        
        console.log(`Resultado - amount: ${payment.amount}, percentage: ${payment.percentage}`);
        
        this.calculateRemaining();
        this.state.hasChanges = true;
        this.savePaymentDistribution();
    }

    savePaymentDistribution() {
        // Preparar datos para guardar con precisión
        const distributionData = this.state.payments.map(p => ({
            payment_method_id: p.id,
            payment_method_name: p.name,
            shopping_code: p.shopping_code,
            payment_code: p.payment_code,
            amount: parseFloat(p.amount.toFixed(2)),
            percentage: parseFloat(p.percentage.toFixed(2))
        }));

        const jsonString = JSON.stringify(distributionData);
        

        // Guardar en el campo del modelo
        this.props.record.update({
            payment_distribution: jsonString
        }).then(() => {
            console.log("✓ Distribución guardada exitosamente en BD");
            this.state.hasChanges = false;
        }).catch((error) => {
            console.error("❌ Error guardando distribución:", error);
        });
    }

    forceManualSave() {
        this.savePaymentDistribution();
    }

    calculateRemaining() {
        if (this.state.inputType === 'amount') {
            const totalAssigned = this.state.payments.reduce((sum, p) => sum + (p.amount || 0), 0);
            this.state.remainingAmount = this.state.totalAmount - totalAssigned;
            this.state.remainingPercentage = this.state.totalAmount > 0
                ? (this.state.remainingAmount / this.state.totalAmount) * 100
                : 0;
        } else {
            const totalPercentage = this.state.payments.reduce((sum, p) => sum + (p.percentage || 0), 0);
            this.state.remainingPercentage = 100 - totalPercentage;
            this.state.remainingAmount = (this.state.remainingPercentage / 100) * this.state.totalAmount;
        }
        
        console.log("Remaining calculado - amount:", this.state.remainingAmount, "percentage:", this.state.remainingPercentage);
    }

    getRemainingColor() {
        const remaining = this.state.inputType === 'amount' 
            ? this.state.remainingAmount 
            : this.state.remainingPercentage;
        
        if (Math.abs(remaining) < 0.01) return 'text-success';
        if (remaining < 0) return 'text-danger';
        return 'text-warning';
    }

    getStatusMessage() {
        const total = this.state.totalAmount;
        const assigned = this.state.payments.reduce((sum, p) => sum + (p.amount || 0), 0);
        
        if (Math.abs(total - assigned) < 0.01) {
            return '✓ Distribución completa';
        } else if (assigned > total) {
            return '⚠ Excede el total';
        } else if (assigned > 0) {
            return '⚠ Distribución incompleta';
        } else {
            return 'Sin asignar';
        }
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('es-UY', {
            style: 'currency',
            currency: 'UYU',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(amount || 0);
    }
}

registry.category("view_widgets").add("account_move_widget", {
    component: AccountMoveWidget,
});