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
        // Snapshot del empleado/vendedor de la orden actual antes de que cambie.
        const currentOrder = this.pos.get_order();
        this.state = useState({
            cfeData: {},
            receiptData: null,
            ocaVoucher: {},
            ocaVouchers: [],
            snapshotSeller: currentOrder?.employee_id?.name || '',
            deductedPoints: [],
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
        // El caller (printReceipt en odoo_pos_no_invoice / pos_forum_qz_print) ya
        // pre-obtuvo cfe_data/oca_vouchers/receiptServerData antes de montar este
        // componente vía renderer.toHtml(). Repetir esas mismas RPC acá (async,
        // post-mount) dispara nuevas mutaciones de this.state mientras el
        // RenderContainer aislado intenta capturar el render, lo que deja el Fiber
        // de Owl sin completar nunca (renderer.toHtml() termina resolviendo null).
        // templateProps ya sabe usar props.data.* como fallback, así que alcanza con
        // no relanzar el fetch.
        if (this.props.data?._skipAsyncReload) {
            console.log('✓ _loadReceiptData omitido: props.data ya viene pre-cargado por el caller (print).');
            return;
        }

        // Si venimos de ReprintReceiptScreen (props.data no tiene cfe_data),
        // usar los datos pre-obtenidos por reprint_receipt_button y limpiarlos.
        const propsCfe = this.props.data?.cfe_data;
        const propsCfeHasData = propsCfe && (propsCfe.tipo || propsCfe.serie || propsCfe.numero);
        if (!propsCfeHasData && this.pos._reprintCfeData &&
            (this.pos._reprintCfeData.tipo || this.pos._reprintCfeData.serie || this.pos._reprintCfeData.numero)) {
            this.state.cfeData = this.pos._reprintCfeData;
            // No nullear: tryReprint() también necesita este dato.
            console.log('✓ CFE data tomado de _reprintCfeData (ReprintReceiptScreen):', this.state.cfeData);
            return;
        }

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

        // Reembolso/orden mixta: deductLoyaltyPoints() (advanced_loyalty_management,
        // CybroAddons) calcula puntos perdidos y saldo nuevo del cliente, pero MUTA
        // order.lostPoints como efecto colateral. Nunca llamarlo desde dentro de
        // templateProps (getter evaluado durante el render de Owl): escribir sobre la
        // orden reactiva ahí dispara un re-render que vuelve a llamar templateProps,
        // que lo vuelve a llamar... un loop que traba el navegador. Se calcula acá,
        // en la carga async post-mount, y se guarda en this.state (que sí es seguro
        // de leer/actualizar desde el getter).
        try {
            const isRefundOrMixedOrder = !!order?._isRefundOrMixedOrder?.();
            this.state.deductedPoints = (isRefundOrMixedOrder && order?.deductLoyaltyPoints)
                ? (order.deductLoyaltyPoints() || [])
                : [];
        } catch (e) {
            console.error('Error al calcular deductLoyaltyPoints:', e);
            this.state.deductedPoints = [];
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
                    if (receiptServerData.source === 'invoice' && receiptServerData.orderlines?.length) {
                        // Factura con líneas completas: usar todos los datos del servidor.
                        this.state.receiptData = receiptServerData;
                        if (!accountMoveId && receiptServerData.account_move_id) {
                            accountMoveId = receiptServerData.account_move_id;
                        }
                        console.log('Datos del recibo (factura) aplicados:', receiptServerData);
                    } else {
                        // Sin líneas de factura: usar solo adenda, moneda y datos auxiliares del servidor.
                        this.state.receiptData = {
                            ...(this.state.receiptData || {}),
                            adenda_data: receiptServerData.adenda_data || {},
                            currency_name: receiptServerData.currency_name || '',
                            legal_data: receiptServerData.legal_data || {},
                        };
                        if (!accountMoveId && receiptServerData.account_move_id) {
                            accountMoveId = receiptServerData.account_move_id;
                        }
                        console.log('Datos auxiliares del servidor aplicados:', receiptServerData);
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
            const rawVouchers = await this.orm.call(
                "pos.order",
                "get_oca_voucher_dict_for_pos_receipt",
                [orderServerId || false, orderReference || false],
            );
            // El backend devuelve una lista; normalizar por si viene un dict legacy.
            const ocaVouchersList = Array.isArray(rawVouchers)
                ? rawVouchers
                : (rawVouchers && typeof rawVouchers === "object" && Object.keys(rawVouchers).length
                    ? [rawVouchers]
                    : []);
            this.state.ocaVouchers = ocaVouchersList;
            this.state.ocaVoucher = ocaVouchersList[0] || {};
            console.info(
                `${OCA_VOUCHER_LOG} _loadReceiptData RPC OK | orderServerId=${orderServerId} ` +
                    `orderReference=${JSON.stringify(orderReference)} | ` +
                    `oca_vouchers_count=${ocaVouchersList.length} | ` +
                    `tickets=${JSON.stringify(ocaVouchersList.map(v => v.ticket_number))}`
            );
        } catch (e) {
            console.warn(`${OCA_VOUCHER_LOG} _loadReceiptData RPC error`, e);
            this.state.ocaVoucher = {};
            this.state.ocaVouchers = [];
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

        // Usar los datos del CFE: preferir state (cargado async), si no, usar props.data.cfe_data
        // (pre-cargado por printReceipt antes de llamar al printer).
        const stateHasCfe = this.state.cfeData &&
            (this.state.cfeData.tipo || this.state.cfeData.serie || this.state.cfeData.numero);
        const cfeData = stateHasCfe ? this.state.cfeData : (this.props.data?.cfe_data || {});
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
        // this.props.data?.adenda_data cubre el render de impresión (nueva instancia sin state).
        const adendaData = {
            cashier: receiptData.adenda_data?.cashier
                || this.props.data?.adenda_data?.cashier
                || this.props.data?.cashier
                || this.props.data?.headerData?.cashier
                || '',
            seller: receiptData.adenda_data?.seller
                || this.props.data?.adenda_data?.seller
                || this.state.snapshotSeller
                || order?.employee_id?.name
                || '',
            points_policy: receiptData.adenda_data?.points_policy
                || this.pos?.config?.pos_points_policy
                || '',
            return_policy: returnPolicyValue,
        };

        // Logo de rutina de impresión: priorizar receipt_logo, luego logo de empresa.
        const receiptLogo = receiptData?.receipt_logo
            || this.pos?.config?.receipt_logo
            || this.props.data?.receipt_logo
            || '';

        // Normalizar nombres de medios de pago (Efectivo_Suc XXX → Efectivo).
        const normalizePaymentName = (name) => {
            if (name && name.toLowerCase().includes('efectivo')) return 'Efectivo';
            return name || '';
        };
        const normalizedPaymentlines = (
            receiptData?.paymentlines?.length
                ? receiptData.paymentlines
                : this.props.data?.paymentlines || []
        ).map(l => ({ ...l, name: normalizePaymentName(l.name) }));

        // Total recibido: suma de todos los medios de pago.
        const totalReceived = receiptData?.total_received
            || normalizedPaymentlines.reduce((acc, l) => acc + (typeof l.amount === 'number' ? l.amount : 0), 0);

        // Construir URL del código de barras para el número de ticket.
        const barcodeValue = this.props.data?.name || legalData.ticket_number || '';
        const baseUrl = this.props.data?.base_url || this.pos?.base_url || '';
        const barcodeSrc = barcodeValue
            ? `${baseUrl}/report/barcode/Code128/${encodeURIComponent(barcodeValue)}?width=600&height=80`
            : '';

        // Log para validar el contenido de CFE en el render del recibo.
        console.log('=== templateProps CFE ===');
        console.log('cfeData:', cfeData);
        console.log('cfeData tiene datos:', !!(cfeData.tipo || cfeData.serie || cfeData.numero));
        console.log('receiptData.adenda_data:', receiptData.adenda_data);
        console.log('seller:', receiptData.adenda_data?.seller, '| order.employee_id:', order?.employee_id?.name);
        console.log('currency_name - receiptData:', receiptData?.currency_name, '| pos.currency:', this.pos?.currency?.name, '| config.currency_id:', this.pos?.config?.currency_id?.name);

        // Construir props combinando datos estándar con los obtenidos del servidor.
        // Definir líneas de pedido priorizando datos del servidor.
        const receiptOrderlines = (receiptData && receiptData.orderlines)
            ? receiptData.orderlines
            : this.props.data.orderlines;

        // Líneas de pago normalizadas (ya procesadas arriba).
        const receiptPaymentlines = (this.props.data?.paymentlines || [])
            .map(l => ({ ...l, name: normalizePaymentName(l.name) }));

        // Bloque: voucher OCA — marcar show_client_copy si hay datos (evita t-if que falle con JSON).
        // oca_voucher: primer elemento (backward compat); oca_vouchers: lista completa.
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
        const ocaVouchers = this.props.data?.oca_vouchers?.length
            ? this.props.data.oca_vouchers
            : (this.state.ocaVouchers?.length
                ? this.state.ocaVouchers
                : (mergedOcaVoucher.show_client_copy ? [mergedOcaVoucher] : []));

        // Log: comprobar si props.data lleva oca_vouchers al diseño QWeb del recibo.
        console.info(
            `${OCA_VOUCHER_LOG} templateProps | oca_vouchers_count=${ocaVouchers.length} ` +
                `show_client_copy=${mergedOcaVoucher.show_client_copy} | fromProps=${JSON.stringify(
                    this.props.data?.oca_voucher || {}
                )} | fromState=${JSON.stringify(this.state.ocaVoucher || {})}`
        );
        // loyaltyStats en props.data es un snapshot tomado por export_for_printing() en el
        // momento del pago/reembolso. Se recalcula acá desde la orden viva (mismo método
        // que usa pos_loyalty) para no depender de cuándo se tomó ese snapshot.
        //
        // advanced_loyalty_management (CybroAddons) pisa getLoyaltyPoints() para que
        // devuelva [] a propósito cuando la orden es reembolso/mixta (order.get_orderlines()
        // con refunded_orderline_id, o total < 0) — ver _isRefundOrMixedOrder() en
        // pos_loyalty_card.js. Para esos casos el saldo/puntos perdidos salen de
        // this.state.deductedPoints, calculado en _loadReceiptData() (no acá: llamar
        // deductLoyaltyPoints() desde este getter muta la orden reactiva en pleno
        // render y puede colgar el navegador en un loop de re-render).
        //
        // Todo el bloque va en try/catch: templateProps también se evalúa cuando
        // printer.print()/renderer.toHtml() monta OrderReceipt fuera de pantalla
        // (botón «Imprimir Boleta», fallback QZ) — ahí una excepción acá deja el
        // render vacío (renderer.toHtml devuelve null) sin ningún error visible más
        // que "Images could not be loaded correctly" en loadAllImages, y el botón
        // de impresión queda sin efecto. Con esta guarda, ante cualquier falla en
        // el cálculo de puntos el recibo igual se imprime, solo sin ese bloque.
        let isRefundOrMixedOrder = false;
        let liveLoyaltyStats = [];
        let liveDeductedPoints = [];
        let loyaltyCurrentBalance = null;
        let pointsLost = 0;
        let loyaltyVisible = false;
        try {
            isRefundOrMixedOrder = !!order?._isRefundOrMixedOrder?.();
            liveLoyaltyStats = order?.getLoyaltyPoints
                ? order.getLoyaltyPoints()
                : (this.props.data?.loyaltyStats || []);
            liveDeductedPoints = this.state.deductedPoints || [];
            const deductedEntry = liveDeductedPoints[0];
            pointsLost = deductedEntry?.lostPoint || 0;
            // Saldo de puntos del cliente ya reflejando este pedido: en venta normal
            // sale de loyaltyStats (balance - spent - points_lost, fórmula que ya
            // usaba el template); en reembolso/mixto sale directo de
            // deductLoyaltyPoints() (newPoint).
            const normalLoyalty = liveLoyaltyStats[0];
            loyaltyCurrentBalance = isRefundOrMixedOrder
                ? parseFloat(deductedEntry?.newPoint ?? 0)
                : (normalLoyalty?.points
                    ? (normalLoyalty.points.balance - normalLoyalty.points.spent - pointsLost)
                    : null);

            // Excluir categorías que no acumulan puntos (ej: Consumidor final, Empleado).
            // partner.category_id en POS es un array de IDs (campo many2many).
            const partnerCategoryIds = partner?.category_id || [];
            const excludedCategoryIds = [1, 2];
            loyaltyVisible = !!(
                (liveLoyaltyStats.length || liveDeductedPoints.length) &&
                !partnerCategoryIds.some(id => excludedCategoryIds.includes(id))
            );
            console.log('ETIQUETAS partner.category_id:', partnerCategoryIds, '| loyalty_visible:', loyaltyVisible);
        } catch (e) {
            console.error('[receipt_cfe_data] Error calculando puntos de lealtad en templateProps:', e);
        }
        console.log(
            '[DEBUG loyaltyStats] order.get_partner():', partner,
            '| isRefundOrMixedOrder:', isRefundOrMixedOrder,
            '| liveLoyaltyStats:', liveLoyaltyStats,
            '| liveDeductedPoints:', liveDeductedPoints,
            '| loyaltyCurrentBalance:', loyaltyCurrentBalance,
            '| couponPointChanges (live order):', order?.couponPointChanges,
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
                cfe_data: cfeData,
                oca_voucher: mergedOcaVoucher,
                oca_vouchers: ocaVouchers,
                receipt_logo: receiptLogo,
                total_received: totalReceived,
                currency_name: receiptData?.currency_name || this.props.data?.currency_name || this.pos?.currency?.name || this.pos?.config?.currency_id?.name || '',
                points_lost: pointsLost,
                loyalty_visible: loyaltyVisible,
                loyaltyStats: liveLoyaltyStats,
                loyalty_is_refund: isRefundOrMixedOrder,
                loyalty_current_balance: loyaltyCurrentBalance,
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