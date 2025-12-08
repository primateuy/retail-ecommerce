/** @odoo-module */
/**
 * Extensión del módulo custom_receipts_for_pos para agregar datos del CFE al recibo
 * 
 * Este módulo extiende el método templateProps del OrderReceipt para incluir
 * la información del Comprobante Fiscal Electrónico (CFE) en el recibo del POS.
 * 
 * Los datos del CFE se obtienen directamente desde el servidor cuando se renderiza
 * el recibo, ya que la orden local puede no tener los datos sincronizados aún.
 */

import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";
import { useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(OrderReceipt.prototype, {
    /**
     * Extiende setup para cargar datos del CFE antes de renderizar
     */
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.state = useState({
            cfeData: {},
        });
        
        // Cargar datos del CFE antes de renderizar el template
        onWillStart(async () => {
            const order = this.pos.get_order();
            if (!order) {
                console.log('No hay orden disponible para cargar datos CFE');
                return;
            }
            
            console.log('=== Cargando datos CFE para recibo ===');
            console.log('Orden:', order.name || order.pos_reference);
            console.log('order.account_move:', order.account_move);
            console.log('order.server_id:', order.server_id);
            console.log('order.id:', order.id);
            
            // Obtener account_move_id desde la orden local
            let accountMoveId = null;
            if (order.account_move) {
                if (Array.isArray(order.account_move)) {
                    accountMoveId = order.account_move[0];
                } else if (typeof order.account_move === 'object' && order.account_move.id) {
                    accountMoveId = order.account_move.id;
                } else if (typeof order.account_move === 'number') {
                    accountMoveId = order.account_move;
                }
                console.log('account_move_id obtenido desde order.account_move:', accountMoveId);
            }
            
            // Si no está en la orden local, buscar en el servidor
            if (!accountMoveId) {
                const orderName = order.name || order.pos_reference;
                const orderRef = order.pos_reference || order.name;
                const orderId = order.server_id || order.id;
                
                console.log('Buscando account_move en servidor para orden:', orderName, 'Ref:', orderRef, 'ID:', orderId);
                
                if (orderName || orderRef) {
                    try {
                        // Buscar orden por pos_reference o name (ambos campos)
                        const searchDomain = [
                            '|',
                            ['pos_reference', '=', orderRef || orderName],
                            ['name', '=', orderName || orderRef]
                        ];
                        
                        console.log('Dominio de búsqueda:', searchDomain);
                        
                        const orders = await this.orm.searchRead(
                            'pos.order',
                            searchDomain,
                            ['id', 'name', 'pos_reference', 'account_move'],
                            { limit: 1 }
                        );
                        
                        console.log('Órdenes encontradas:', orders);
                        
                        if (orders && orders.length > 0) {
                            const foundOrder = orders[0];
                            console.log('Orden encontrada:', foundOrder);
                            
                            if (foundOrder.account_move) {
                                if (Array.isArray(foundOrder.account_move)) {
                                    accountMoveId = foundOrder.account_move[0];
                                } else if (typeof foundOrder.account_move === 'object' && foundOrder.account_move.id) {
                                    accountMoveId = foundOrder.account_move.id;
                                } else {
                                    accountMoveId = foundOrder.account_move;
                                }
                                console.log('account_move_id obtenido desde servidor:', accountMoveId);
                            } else {
                                console.log('Orden encontrada pero sin account_move');
                            }
                        } else {
                            console.log('No se encontró orden en servidor con nombre/referencia:', orderName, orderRef);
                        }
                    } catch (e) {
                        console.error('Error al buscar account_move en servidor:', e);
                    }
                }
            }
            
            // Obtener datos del CFE desde account_move si está disponible
            if (accountMoveId) {
                console.log('Obteniendo datos CFE desde factura ID:', accountMoveId);
                try {
                    const cfeData = await this.orm.call('pos.order', 'get_cfe_data_from_invoice', [[], accountMoveId]) || {};
                    console.log('Datos CFE obtenidos:', cfeData);
                    
                    // Agregar información adicional de la orden
                    if (cfeData && (cfeData.tipo || cfeData.serie || cfeData.numero)) {
                        cfeData.vta_cont = order?.pos_reference || order?.name || '';
                        cfeData.caja = order?.session_id ? (order.session_id.name || '') : '';
                        cfeData.cajero = order?.user_id ? (order.user_id.name || '') : '';
                        cfeData.vend = '0';
                        cfeData.store = order?.config_id ? `STORE-${order.config_id.id}` : '';
                        
                        // Método de pago
                        if (order?.payment_ids && order.payment_ids.length > 0) {
                            const paymentMethod = order.payment_ids[0].payment_method_id;
                            cfeData.pago = paymentMethod ? (paymentMethod.name || 'Contado') : 'Contado';
                        } else {
                            cfeData.pago = 'Contado';
                        }
                        
                        this.state.cfeData = cfeData;
                        console.log('✓ Datos CFE cargados correctamente:', this.state.cfeData);
                    } else {
                        console.log('Factura no tiene datos CFE completos aún');
                    }
                } catch (e) {
                    console.error('Error al obtener datos CFE:', e);
                }
            } else {
                console.log('No se encontró account_move para la orden');
            }
        });
    },

    /**
     * Extiende templateProps para incluir datos del CFE directamente desde account_move
     * 
     * Los datos del CFE se obtienen en onWillStart y se agregan a props.data,
     * igual que el resto de la información del recibo.
     * 
     * @returns {Object} Props extendidos con datos del CFE
     */
    get templateProps() {
        const order = this.pos.get_order();
        const partner = order ? order.get_partner() : null;
        
        // Usar los datos del CFE cargados en onWillStart
        const cfeData = this.state.cfeData || {};
        
        console.log('=== templateProps CFE ===');
        console.log('cfeData:', cfeData);
        console.log('cfeData.tipo:', cfeData.tipo);
        console.log('cfeData.serie:', cfeData.serie);
        console.log('cfeData.numero:', cfeData.numero);
        console.log('cfeData tiene datos:', !!(cfeData.tipo || cfeData.serie || cfeData.numero));

        const props = {
            pos: this.pos,
            data: {
                ...(this.props.data || {}),
                cfe_data: cfeData, // Agregar datos del CFE directamente a props.data
            },
            order: order,
            receipt: this.props.data,
            orderlines: this.props.data.orderlines,
            paymentlines: this.props.data.paymentlines,
            partner: partner,
        };
        
        // Log final para verificar que los datos estén en props.data
        console.log('props.data.cfe_data:', props.data.cfe_data);
        console.log('props.data.cfe_data?.tipo:', props.data.cfe_data?.tipo);
        console.log('props.data.cfe_data?.serie:', props.data.cfe_data?.serie);
        console.log('props.data.cfe_data?.numero:', props.data.cfe_data?.numero);
        
        return props;
    },
});

