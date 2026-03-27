/** @odoo-module */
/**
 * Extensión del módulo custom_receipts_for_pos para agregar datos del CFE al recibo
 * 
 * Este módulo extiende el método templateProps del OrderReceipt para incluir
 * la información del Comprobante Fiscal Electrónico (CFE) en el recibo del POS.
 * 
 * Los datos del CFE se obtienen directamente desde el servidor cuando se renderiza
 * el recibo, ya que la orden local puede no tener los datos sincronizados aún.
 *
 * El bundle POS debe cargar este archivo después de custom_receipts_for_pos para que
 * este patch de templateProps reemplace al de receipt_design.js (ver __manifest__.py).
 */

import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { patch } from "@web/core/utils/patch";
import { useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/** Prefijo fijo para filtrar en consola (F12) al depurar el bloque voucher OCA en el recibo. */
const OCA_VOUCHER_LOG = "[odoo_pos_no_invoice][oca_voucher]";

patch(OrderReceipt.prototype, {
    /**
     * Extiende setup para cargar datos del CFE antes de renderizar
     */
    setup() {
        // Ejecutar el setup estándar del componente para mantener el ciclo de vida base.
        super.setup();
        // Obtener servicio ORM para llamadas al backend desde el POS.
        this.orm = useService("orm");
        // Inicializar el estado local con los datos necesarios para el recibo.
        this.state = useState({
            cfeData: {},
            receiptData: null,
            ocaVoucher: {},
        });
        
        // Cargar datos del recibo y CFE sin bloquear el render del ticket.
        onMounted(() => {
            this._loadReceiptData();
        });
    },

    /**
     * Carga en segundo plano los datos del recibo y del CFE.
     */
    async _loadReceiptData() {
        // Obtener la orden actual si existe en el POS.
        const order = this.pos.get_order();
        // Preparar referencia de orden para búsquedas en servidor.
        const receiptData = this.props.data || {};
        const orderReference = (
            order?.pos_reference ||
            order?.name ||
            receiptData?.pos_reference ||
            receiptData?.name ||
            receiptData?.order_name ||
            ''
        );
        const orderServerId = order?.server_id || null;
        if (!order) {
            console.log('No hay orden disponible en el POS, se usará referencia del recibo');
        }
        
        // Registrar información de contexto para depuración controlada.
        console.log('=== Cargando datos CFE para recibo ===');
        if (order) {
            console.log('Orden:', order.name || order.pos_reference);
            console.log('order.account_move:', order.account_move);
            console.log('order.server_id:', order.server_id);
            console.log('order.id:', order.id);
        }
        
        // Obtener account_move_id desde la orden local.
        let accountMoveId = null;
        if (order && order.account_move) {
            if (Array.isArray(order.account_move)) {
                accountMoveId = order.account_move[0];
            } else if (typeof order.account_move === 'object' && order.account_move.id) {
                accountMoveId = order.account_move.id;
            } else if (typeof order.account_move === 'number') {
                accountMoveId = order.account_move;
            }
            console.log('account_move_id obtenido desde order.account_move:', accountMoveId);
        }
        
        // Obtener datos completos del recibo desde la factura y hacer fallback a la orden.
            try {
                const receiptServerData = await this.orm.call(
                    'pos.order',
                    'get_receipt_data_from_invoice_or_order',
                    [[], accountMoveId, orderReference, orderServerId]
                );
                if (receiptServerData) {
                    // Solo actualizar el estado si la factura trae líneas completas.
                    if (receiptServerData.source === 'invoice' && receiptServerData.orderlines?.length) {
                        this.state.receiptData = receiptServerData;
                        if (!accountMoveId && receiptServerData.account_move_id) {
                            accountMoveId = receiptServerData.account_move_id;
                        }
                        console.log('Datos del recibo (factura) aplicados:', receiptServerData);
                    } else {
                        console.log('Datos del recibo incompletos, se mantiene el POS:', receiptServerData);
                    }
                }
            } catch (e) {
            console.error('Error al obtener datos del recibo desde servidor:', e);
        }
        
        // Obtener datos del CFE desde account_move si está disponible.
        if (accountMoveId) {
            console.log('Obteniendo datos CFE desde factura ID:', accountMoveId);
            try {
                const cfeData = await this.orm.call('pos.order', 'get_cfe_data_from_invoice', [[], accountMoveId]) || {};
                console.log('Datos CFE obtenidos:', cfeData);
                
                // Agregar información adicional de la orden para la adenda.
                if (cfeData && (cfeData.tipo || cfeData.serie || cfeData.numero)) {
                    cfeData.vta_cont = order?.pos_reference || order?.name || '';
                    cfeData.caja = order?.session_id ? (order.session_id.name || '') : '';
                    cfeData.cajero = order?.user_id ? (order.user_id.name || '') : '';
                    cfeData.vend = '0';
                    cfeData.store = order?.config_id ? `STORE-${order.config_id.id}` : '';
                    
                    // Método de pago utilizado en la operación.
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

        // Bloque: datos del voucher OCA para el recibo «FORUM» (copia cliente en el ticket de compra).
        try {
            const ocaVoucher = await this.orm.call(
                "pos.order",
                "get_oca_voucher_dict_for_pos_receipt",
                [orderServerId || false, orderReference || false],
            );
            this.state.ocaVoucher =
                ocaVoucher && typeof ocaVoucher === "object" ? ocaVoucher : {};
            // Log: trazar respuesta RPC para ver si el backend devuelve {} (sin transacción) o datos.
            console.info(
                `${OCA_VOUCHER_LOG} _loadReceiptData RPC OK | orderServerId=${orderServerId} ` +
                    `orderReference=${JSON.stringify(orderReference)} | keys=${Object.keys(
                        this.state.ocaVoucher
                    ).join(",")} | has_voucher=${this.state.ocaVoucher.has_voucher} ` +
                    `show_client_copy=${this.state.ocaVoucher.show_client_copy} | payload=${JSON.stringify(
                        this.state.ocaVoucher
                    )}`
            );
        } catch (e) {
            console.warn(`${OCA_VOUCHER_LOG} _loadReceiptData RPC error`, e);
            this.state.ocaVoucher = {};
        }
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
        // Recuperar la orden actual del POS para datos contextuales.
        const order = this.pos.get_order();
        // Recuperar el partner asociado a la orden si existe.
        const partner = order ? order.get_partner() : null;
        
        // Usar los datos del CFE cargados en onWillStart.
        const cfeData = this.state.cfeData || {};
        // Usar los datos del recibo cargados desde factura/orden.
        const receiptData = this.state.receiptData || {};
        
        // Definir datos legales con fallback a la información local del POS.
        const legalData = {
            purchase_condition: receiptData.legal_data?.purchase_condition
                || this.props.data?.paymentlines?.[0]?.name
                || '',
            ticket_number: receiptData.legal_data?.ticket_number
                || cfeData?.cfe_serie_num
                || this.props.data?.name
                || '',
            date: receiptData.legal_data?.date
                || this.props.data?.date
                || '',
            document_type: receiptData.legal_data?.document_type
                || cfeData?.tipo
                || '',
            customer_name: receiptData.legal_data?.customer_name
                || partner?.name
                || 'Consumidor final',
            branch_name: receiptData.legal_data?.branch_name
                || this.pos?.config?.name
                || '',
        };

        // Determinar política de cambio desde adenda o desde el footer del POS.
        const footerHtml = this.props.data?.footer_html || '';
        const footerText = this.props.data?.footer || '';
        const hasFooterPolicy = !receiptData.adenda_data?.return_policy && (footerHtml || footerText);
        const returnPolicyValue = receiptData.adenda_data?.return_policy || footerHtml || footerText || '';

        // Definir datos de adenda con fallback a la información local del POS.
        const adendaData = {
            cashier: receiptData.adenda_data?.cashier
                || this.props.data?.cashier
                || this.props.data?.headerData?.cashier
                || '',
            seller: receiptData.adenda_data?.seller || '',
            points_policy: receiptData.adenda_data?.points_policy
                || this.pos?.config?.pos_points_policy
                || '',
            return_policy: returnPolicyValue,
        };

        // Construir URL del código de barras para el número de ticket.
        const barcodeValue = legalData.ticket_number || this.props.data?.name || '';
        const baseUrl = this.props.data?.base_url || this.pos?.base_url || '';
        const barcodeSrc = barcodeValue
            ? `${baseUrl}/report/barcode/Code128/${encodeURIComponent(barcodeValue)}?width=300&height=80`
            : '';
        
        // Log para validar el contenido de CFE en el render del recibo.
        console.log('=== templateProps CFE ===');
        console.log('cfeData:', cfeData);
        console.log('cfeData.tipo:', cfeData.tipo);
        console.log('cfeData.serie:', cfeData.serie);
        console.log('cfeData.numero:', cfeData.numero);
        console.log('cfeData tiene datos:', !!(cfeData.tipo || cfeData.serie || cfeData.numero));

        // Construir props combinando datos estándar con los obtenidos del servidor.
        // Definir líneas de pedido priorizando datos del servidor.
        const receiptOrderlines = (receiptData && receiptData.orderlines)
            ? receiptData.orderlines
            : this.props.data.orderlines;

        // Definir líneas de pago priorizando datos del servidor.
        const receiptPaymentlines = (receiptData && receiptData.paymentlines)
            ? receiptData.paymentlines
            : this.props.data.paymentlines;

        // Bloque: voucher OCA — marcar show_client_copy si hay datos (evita t-if que falle con JSON).
        const mergedOcaVoucher = {
            ...(this.props.data?.oca_voucher || {}),
            ...(this.state.ocaVoucher || {}),
        };
        if (
            mergedOcaVoucher &&
            (mergedOcaVoucher.has_voucher ||
                mergedOcaVoucher.show_client_copy ||
                mergedOcaVoucher.ticket_number ||
                typeof mergedOcaVoucher.amount === "number")
        ) {
            mergedOcaVoucher.show_client_copy = true;
        }

        // Log: comprobar si props.data lleva oca_voucher al diseño QWeb del recibo (condición t-if).
        console.info(
            `${OCA_VOUCHER_LOG} templateProps | mergedKeys=${Object.keys(mergedOcaVoucher).length} ` +
                `show_client_copy=${mergedOcaVoucher.show_client_copy} | fromProps=${JSON.stringify(
                    this.props.data?.oca_voucher || {}
                )} | fromState=${JSON.stringify(this.state.ocaVoucher || {})}`
        );

        // Construir objeto final de props para el template del recibo.
        const props = {
            pos: this.pos,
            data: {
                ...(this.props.data || {}),
                ...(receiptData || {}),
                skip_footer: !!hasFooterPolicy,
                barcode_value: barcodeValue,
                barcode_src: barcodeSrc,
                legal_data: legalData,
                adenda_data: adendaData,
                cfe_data: cfeData, // Agregar datos del CFE directamente a props.data
                oca_voucher: mergedOcaVoucher,
            },
            order: order,
            receipt: this.props.data,
            orderlines: receiptOrderlines,
            paymentlines: receiptPaymentlines,
            partner: partner,
        };
        
        // Log final para verificar que los datos estén en props.data.
        console.log('props.data.cfe_data:', props.data.cfe_data);
        console.log('props.data.cfe_data?.tipo:', props.data.cfe_data?.tipo);
        console.log('props.data.cfe_data?.serie:', props.data.cfe_data?.serie);
        console.log('props.data.cfe_data?.numero:', props.data.cfe_data?.numero);
        
        return props;
    },
});

