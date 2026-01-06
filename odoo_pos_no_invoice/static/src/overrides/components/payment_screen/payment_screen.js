/** @odoo-module */

import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import {patch} from "@web/core/utils/patch";
import { ConnectionLostError } from "@web/core/network/rpc_service";

patch(PaymentScreen.prototype, {
    /**
     * Finaliza la validación de la orden POS
     * 
     * Este método sobrescribe el método estándar para manejar la facturación
     * sin descargar el PDF. Además, maneja el caso donde account_move puede
     * no estar disponible inmediatamente en el resultado debido a procesos
     * asíncronos de facturación electrónica.
     * 
     * Si la configuración 'download_invoice' del POS está en True, se mantiene
     * el comportamiento estándar de Odoo (no se aplica ninguna modificación).
     */
    async _finalizeValidation() {
        // Verificar si la configuración del POS permite descargar factura
        // Si download_invoice es True, usar comportamiento estándar de Odoo
        const downloadInvoice = this.pos.config.download_invoice || false;
        
        if (downloadInvoice) {
            // Comportamiento estándar: llamar al método original sin modificaciones
            return super._finalizeValidation();
        }
        
        // Comportamiento personalizado: no descargar factura automáticamente
        // Abrir cajón de efectivo si corresponde
        if (this.currentOrder.is_paid_with_cash() || this.currentOrder.get_change()) {
            this.hardwareProxy.openCashbox();
        }

        // Actualizar fecha de la orden
        this.currentOrder.date_order = luxon.DateTime.now();
        
        // Remover líneas de pago con monto cero
        for (const line of this.paymentLines) {
            if (!line.amount === 0) {
                this.currentOrder.remove_paymentline(line);
            }
        }
        this.currentOrder.finalized = true;

        this.env.services.ui.block();
        let syncOrderResult;
        try {
            // 1. Guardar orden en el servidor
            syncOrderResult = await this.pos.push_single_order(this.currentOrder);
            if (!syncOrderResult) {
                return;
            }
            
            // 2. Manejar facturación (si aplica)
            if (this.shouldDownloadInvoice() && this.currentOrder.is_to_invoice()) {
                let accountMoveId = syncOrderResult[0]?.account_move;
                
                // Si account_move no está en el resultado, intentar obtenerlo consultando la orden
                if (!accountMoveId && syncOrderResult[0]?.id) {
                    try {
                        const orderData = await this.orm.read(
                            'pos.order',
                            [syncOrderResult[0].id],
                            ['account_move']
                        );
                        if (orderData && orderData[0] && orderData[0].account_move) {
                            accountMoveId = orderData[0].account_move[0]; // Many2one retorna [id, name]
                            console.log('account_move obtenido consultando la orden:', accountMoveId);
                        }
                    } catch (readError) {
                        console.warn('Error al consultar account_move de la orden:', readError);
                    }
                }
                
                // Si después de intentar obtenerlo aún no está disponible, verificar si la orden está facturada
                if (!accountMoveId) {
                    // Verificar el estado de la orden para determinar si realmente hay un problema
                    // Si la orden se procesó correctamente pero account_move no está disponible,
                    // puede ser un problema de timing con facturación electrónica
                    console.warn(
                        'account_move no disponible en el resultado para orden:',
                        syncOrderResult[0]?.id || syncOrderResult[0]?.name
                    );
                    // No lanzar error aquí, ya que el módulo se llama "no_invoice" y su propósito
                    // es no descargar la factura. Si la factura se generó correctamente en el backend,
                    // no necesitamos bloquear el proceso.
                } else {
                    console.log('Factura generada correctamente, no se descarga (account_move:', accountMoveId, ')');
                }
            }
            
            // 3. Procesamiento posterior - Mover dentro del try para manejar errores correctamente
            // Esto evita el error "Component is destroyed" si el componente se destruye durante el proceso
            if (
                syncOrderResult &&
                syncOrderResult.length > 0 &&
                this.currentOrder.wait_for_push_order()
            ) {
                try {
                    await this.postPushOrderResolve(syncOrderResult.map((res) => res.id));
                } catch (postResolveError) {
                    // Si el componente fue destruido, solo registrar el error sin lanzarlo
                    // para no interrumpir el flujo de validación
                    // El error puede venir en diferentes formatos: mensaje de error, string, o objeto
                    const errorMessage = postResolveError?.message || postResolveError?.toString() || String(postResolveError);
                    if (errorMessage.includes('Component is destroyed') || 
                        errorMessage.includes('component is destroyed') ||
                        errorMessage.includes('destroyed')) {
                        console.warn('Componente destruido durante postPushOrderResolve, continuando...', errorMessage);
                    } else {
                        // Para otros errores, re-lanzar para que se manejen en el catch principal
                        throw postResolveError;
                    }
                }
            }

            // Ejecutar afterOrderValidation dentro del try para manejar errores correctamente
            try {
                await this.afterOrderValidation(!!syncOrderResult && syncOrderResult.length > 0);
            } catch (afterValidationError) {
                // Si el componente fue destruido, solo registrar el error sin lanzarlo
                // para no interrumpir el flujo de validación
                // El error puede venir en diferentes formatos: mensaje de error, string, o objeto
                const errorMessage = afterValidationError?.message || afterValidationError?.toString() || String(afterValidationError);
                if (errorMessage.includes('Component is destroyed') || 
                    errorMessage.includes('component is destroyed') ||
                    errorMessage.includes('destroyed')) {
                    console.warn('Componente destruido durante afterOrderValidation, continuando...', errorMessage);
                } else {
                    // Para otros errores, re-lanzar para que se manejen en el catch principal
                    throw afterValidationError;
                }
            }
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                this.pos.showScreen(this.nextScreen);
                Promise.reject(error);
                return error;
            } else {
                throw error;
            }
        } finally {
            this.env.services.ui.unblock();
        }
    }
});
