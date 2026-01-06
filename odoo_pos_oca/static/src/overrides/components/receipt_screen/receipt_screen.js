/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * Extensión de ReceiptScreen para agregar funcionalidad de Ticket de Cambio
 * 
 * Este módulo agrega un botón "Ticket de cambio" que permite imprimir
 * un reporte configurable desde la configuración del POS.
 * 
 * El botón se agrega dinámicamente desde JavaScript después de que todo esté renderizado
 * para evitar interferir con el sistema de impresión que usa cloneNode.
 */
patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.report = useService("report");
        
        // Agregar el botón después de que el componente esté completamente montado
        // Usamos un delay largo para asegurar que el sistema de impresión esté completamente inicializado
        onMounted(() => {
            // Delay largo para asegurar que el botón de imprimir esté completamente renderizado
            // y que el sistema de impresión haya terminado de inicializarse
            setTimeout(() => {
                this._addChangeTicketButtonSafely();
            }, 500);
        });
        
        onWillUnmount(() => {
            this._removeChangeTicketButton();
        });
    },

    /**
     * Agrega el botón de ticket de cambio de manera segura sin interferir con la impresión
     * 
     * Este método busca el contenedor del botón de imprimir recibo y agrega
     * el botón de ticket de cambio justo después, sin tocar el botón de imprimir.
     */
    _addChangeTicketButtonSafely() {
        // Verificar que haya un reporte configurado
        if (!this.pos.config.change_ticket_report_id) {
            return;
        }

        // Verificar si el botón ya existe
        if (document.querySelector('.print-change-ticket-button')) {
            return;
        }

        // Buscar el área de acciones
        const screenContent = this.el?.querySelector('.screen-content') ||
                             document.querySelector('.receipt-screen .screen-content');
        
        if (!screenContent) {
            return;
        }

        const actionsArea = screenContent.querySelector('.actions');
        
        if (!actionsArea) {
            return;
        }

        // Buscar el contenedor del botón de imprimir recibo
        // El botón de imprimir está dentro de un div.buttons
        const printButtonContainer = actionsArea.querySelector('.buttons');
        
        if (!printButtonContainer) {
            // Si no encontramos el contenedor, agregar al final del área de acciones
            // como fallback
            const newButtonContainer = document.createElement('div');
            newButtonContainer.className = 'change-ticket-container mt-3';
            newButtonContainer.style.marginTop = '1rem';
            
            const changeTicketButton = document.createElement('button');
            changeTicketButton.className = 'button print-change-ticket-button btn btn-secondary w-100 py-3';
            changeTicketButton.innerHTML = '<i class="fa fa-exchange-alt ms-2"></i><span>Ticket de cambio</span>';
            changeTicketButton.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.printChangeTicket();
            };
            
            newButtonContainer.appendChild(changeTicketButton);
            actionsArea.appendChild(newButtonContainer);
            return;
        }

        // Crear un contenedor nuevo para nuestro botón
        // Lo insertamos justo después del contenedor del botón de imprimir
        const newButtonContainer = document.createElement('div');
        newButtonContainer.className = 'change-ticket-container';
        newButtonContainer.style.marginTop = '0.5rem';
        
        // Crear el botón
        const changeTicketButton = document.createElement('button');
        changeTicketButton.className = 'button print-change-ticket-button btn btn-secondary w-100 py-3';
        changeTicketButton.innerHTML = '<i class="fa fa-exchange-alt ms-2"></i><span>Ticket de cambio</span>';
        changeTicketButton.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.printChangeTicket();
        };
        
        // Agregar el botón al contenedor
        newButtonContainer.appendChild(changeTicketButton);
        
        // Insertar el contenedor justo después del contenedor del botón de imprimir
        // Esto lo coloca debajo del botón "Imprimir recibo" sin tocar ese botón
        if (printButtonContainer.nextSibling) {
            printButtonContainer.parentNode.insertBefore(newButtonContainer, printButtonContainer.nextSibling);
        } else {
            printButtonContainer.parentNode.appendChild(newButtonContainer);
        }
    },

    /**
     * Remueve el botón de ticket de cambio del DOM
     */
    _removeChangeTicketButton() {
        const container = document.querySelector('.change-ticket-container');
        if (container) {
            container.remove();
        }
    },

    /**
     * Imprime el ticket de cambio usando el reporte configurado en pos.config
     * 
     * Este método obtiene el reporte configurado en change_ticket_report_id
     * y lo imprime para la orden actual.
     * 
     * @returns {Promise} Promesa que se resuelve cuando se completa la impresión
     */
    async printChangeTicket() {
        try {
            // Verificar que haya un reporte configurado
            if (!this.pos.config.change_ticket_report_id) {
                // Mostrar mensaje de error si no hay reporte configurado
                // Usar el servicio de notificaciones del entorno
                this.env.services.notification.add(
                    'No hay un reporte de ticket de cambio configurado. Por favor, configure uno en la configuración del POS.',
                    { type: 'warning' }
                );
                return;
            }

            // Obtener la orden actual usando el método estándar de POS
            // En ReceiptScreen, la orden se obtiene con this.pos.get_order()
            const order = this.pos.get_order();
            if (!order) {
                this.env.services.notification.add(
                    'No se encontró la orden para imprimir el ticket de cambio.',
                    { type: 'warning' }
                );
                return;
            }

            // Obtener el ID de la orden desde el backend
            // La orden puede tener server_id (ID del servidor cuando está guardada) o id (ID local)
            // Priorizamos server_id porque es el ID real en el servidor
            let orderId = order.server_id || order.id;
            
            // Si no tenemos server_id, intentar obtenerlo desde los datos exportados
            // que contienen la información de la orden guardada
            if (!orderId) {
                try {
                    const orderData = order.export_for_printing();
                    if (orderData && orderData.id) {
                        orderId = orderData.id;
                    }
                } catch (e) {
                    console.warn('No se pudo obtener ID desde export_for_printing:', e);
                }
            }
            
            // Si aún no tenemos ID, buscar la orden en el servidor por su referencia
            if (!orderId && (order.name || order.pos_reference)) {
                try {
                    const orderRef = order.name || order.pos_reference;
                    const searchResult = await this.orm.searchRead(
                        'pos.order',
                        [
                            '|',
                            ['name', '=', orderRef],
                            ['pos_reference', '=', orderRef]
                        ],
                        ['id'],
                        { limit: 1 }
                    );
                    
                    if (searchResult && searchResult.length > 0) {
                        orderId = searchResult[0].id;
                    }
                } catch (e) {
                    console.warn('Error al buscar orden en servidor:', e);
                }
            }

            if (!orderId) {
                this.env.services.notification.add(
                    'La orden aún no ha sido guardada en el servidor. Por favor, espere un momento e intente nuevamente.',
                    { type: 'warning' }
                );
                return;
            }

            // Obtener el ID del reporte configurado
            // Many2one puede retornar [id, name] o solo el id
            const reportId = Array.isArray(this.pos.config.change_ticket_report_id) 
                ? this.pos.config.change_ticket_report_id[0] 
                : this.pos.config.change_ticket_report_id;

            // Obtener el XML ID completo de la acción de reporte desde el servidor
            // El servicio de reporte en POS necesita el XML ID completo de la acción
            let reportXmlId = null;
            try {
                // Obtener el XML ID desde ir.model.data usando el ID del reporte
                const modelData = await this.orm.searchRead(
                    'ir.model.data',
                    [
                        ['model', '=', 'ir.actions.report'],
                        ['res_id', '=', reportId]
                    ],
                    ['module', 'name'],
                    { limit: 1 }
                );
                
                if (modelData && modelData.length > 0) {
                    // Construir el XML ID completo: module.name
                    reportXmlId = `${modelData[0].module}.${modelData[0].name}`;
                } else {
                    // Fallback: usar el XML ID esperado según el archivo de datos
                    reportXmlId = 'odoo_pos_oca.action_report_pos_order_change_ticket';
                }
            } catch (e) {
                console.error('Error al obtener XML ID del reporte:', e);
                // Fallback: usar el XML ID esperado directamente
                reportXmlId = 'odoo_pos_oca.action_report_pos_order_change_ticket';
            }

            if (!reportXmlId) {
                this.env.services.notification.add(
                    'No se pudo obtener el identificador del reporte configurado.',
                    { type: 'warning' }
                );
                return;
            }

            // Llamar al servicio de reporte para imprimir usando doAction
            // El formato correcto es: doAction(reportXmlId, [array_de_ids])
            await this.report.doAction(reportXmlId, [orderId]);

            // Notificación de éxito
            this.env.services.notification.add(
                'Ticket de cambio impreso correctamente.',
                { type: 'success' }
            );
        } catch (error) {
            // Manejar errores durante la impresión
            console.error('Error al imprimir ticket de cambio:', error);
            const errorMessage = error?.message || error?.toString() || String(error);
            this.env.services.notification.add(
                `Error al imprimir ticket de cambio: ${errorMessage}`,
                { type: 'danger' }
            );
        }
    },
});
