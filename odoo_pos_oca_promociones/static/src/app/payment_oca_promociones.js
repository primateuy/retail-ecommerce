/** @odoo-module */

import {patch} from "@web/core/utils/patch";
import {PaymentOCA} from "@odoo_pos_oca/app/payment_oca";

/**
 * Extensión de PaymentOCA para soporte de promociones
 * 
 * Agrega funcionalidad para:
 * - Enviar flag NeedToReadCard para obtener datos de tarjeta
 * - Detectar ResponseCode = 12 con datos de tarjeta
 * - Procesar promociones y agregar líneas de descuento
 * - Confirmar transacciones con montos modificados
 */
patch(PaymentOCA.prototype, {
    /**
     * Obtiene el nro de cuotas desde la línea de pago del POS.
     * Si la línea tiene installments definido y > 0 se usa; si no, 1.
     * Así se respeta siempre el valor elegido por el usuario (ej. pagar en 3 cuotas).
     *
     * @param {Object} paymentLine - Línea de pago (order.selected_paymentline o similar)
     * @returns {number} Número de cuotas (entero >= 1)
     */
    _getInstallmentsFromPaymentLine(paymentLine) {
        if (!paymentLine) return 1;
        const n = paymentLine.installments;
        if (n !== undefined && n !== null) {
            const parsed = parseInt(n, 10);
            if (!isNaN(parsed) && parsed >= 1) return parsed;
        }
        return 1;
    },

    /**
     * ID de pos.order en el servidor para validar incompatibilidades (lealtad vs promo OCA).
     */
    _getServerPosOrderId(order) {
        if (!order) {
            return false;
        }
        const raw =
            order.server_id != null && order.server_id !== false
                ? order.server_id
                : order.id;
        if (raw == null || raw === false) {
            return false;
        }
        const parsed = parseInt(raw, 10);
        if (Number.isNaN(parsed) || parsed <= 0) {
            return false;
        }
        return parsed;
    },

    _loyaltyModels() {
        return this.pos?.models || this.pos?.data?.models || {};
    },

    _normalizeProgramId(raw) {
        if (raw == null || raw === false) {
            return null;
        }
        if (Array.isArray(raw)) {
            return this._normalizeProgramId(raw[0]);
        }
        if (typeof raw === "object" && raw.id != null) {
            return Number(raw.id);
        }
        const n = Number(raw);
        return Number.isNaN(n) ? null : n;
    },

    /**
     * loyalty.program aplicados en el carrito actual (para payload OCA y snapshot en sesión).
     *
     * Odoo 17 + pos_loyalty usa reward_by_id, couponCache, líneas de pedido, etc.
     *
     * Importante: NO usamos order.couponPointChanges para este conjunto. Ese mapa suele
     * seguir referenciando el programa después de borrar la línea de descuento (acumulación
     * de puntos / estado interno), lo que provocaba bloqueos falsos al volver a cobrar con
     * promo OCA. La incompatibilidad debe basarse en beneficios aún presentes en líneas
     * o cupones activados por código.
     */
    _collectAppliedLoyaltyProgramIdsFromPosOrder(order) {
        const ids = new Set();
        const pos = this.pos;
        if (!order) {
            return [];
        }

        const fromCodeCoupons = [];
        const cac = order.codeActivatedCoupons;
        if (Array.isArray(cac)) {
            for (const c of cac) {
                const pid = this._normalizeProgramId(c?.program_id);
                if (pid) {
                    ids.add(pid);
                    fromCodeCoupons.push(pid);
                }
            }
        }

        let lines = [];
        if (typeof order.get_orderlines === "function") {
            lines = order.get_orderlines() || [];
        } else if (Array.isArray(order.orderlines)) {
            lines = order.orderlines;
        }

        const fromLinesReward = [];
        const fromLinesCoupon = [];
        const fromLinesDirect = [];

        for (const line of lines) {
            const directPid = this._normalizeProgramId(line.program_id);
            if (directPid) {
                ids.add(directPid);
                fromLinesDirect.push(directPid);
            }

            let rewardId = line.reward_id;
            if (Array.isArray(rewardId)) {
                rewardId = rewardId[0];
            }
            if (rewardId && pos.reward_by_id) {
                const reward = pos.reward_by_id[rewardId];
                const programId = this._normalizeProgramId(reward?.program_id);
                if (programId) {
                    ids.add(programId);
                    fromLinesReward.push(programId);
                }
            }

            let couponId = line.coupon_id;
            if (Array.isArray(couponId)) {
                couponId = couponId[0];
            }
            if (couponId != null && pos.couponCache) {
                const card = pos.couponCache[couponId];
                const programId = this._normalizeProgramId(card?.program_id);
                if (programId) {
                    ids.add(programId);
                    fromLinesCoupon.push(programId);
                }
            }

            const models = this._loyaltyModels();
            const RewardModel = models["loyalty.reward"];
            const CardModel = models["loyalty.card"];
            if (rewardId && RewardModel && typeof RewardModel.get === "function") {
                const reward = RewardModel.get(rewardId);
                const programId = this._normalizeProgramId(reward?.program_id);
                if (programId) {
                    ids.add(programId);
                }
            }
            if (couponId && CardModel && typeof CardModel.get === "function") {
                const card = CardModel.get(couponId);
                const programId = this._normalizeProgramId(card?.program_id);
                if (programId) {
                    ids.add(programId);
                }
            }
        }

        const out = Array.from(ids);
        // --- Log de diagnóstico: couponPointChanges solo informativo (no entra en FINAL) ---
        const cpcDebug = [];
        const cpc = order.couponPointChanges;
        if (cpc && typeof cpc === "object") {
            for (const pe of Object.values(cpc)) {
                const pid = this._normalizeProgramId(pe?.program_id);
                if (pid) {
                    cpcDebug.push(pid);
                }
            }
        }
        console.info(
            "[OCA_PROMOS] _collectAppliedLoyaltyProgramIdsFromPosOrder | FINAL=%s | " +
                "couponPointChanges(solo_log)=%s | codeActivatedCoupons=%s | líneas reward_by_id=%s | " +
                "líneas couponCache=%s | líneas program_id=%s | n_líneas=%s",
            JSON.stringify(out),
            JSON.stringify(cpcDebug),
            JSON.stringify(fromCodeCoupons),
            JSON.stringify(fromLinesReward),
            JSON.stringify(fromLinesCoupon),
            JSON.stringify(fromLinesDirect),
            lines.length
        );
        return out;
    },

    /**
     * Guarda en pos.session los programas de lealtad del carrito para el hilo OCA (sin depender del borrador).
     */
    async _syncOcaCartLoyaltyProgramsToSession(order) {
        const sid = order?.pos_session_id;
        if (!sid) {
            console.info(
                "[OCA_PROMOS] _syncOcaCartLoyaltyProgramsToSession: sin pos_session_id en orden, no se persiste lealtad"
            );
            return;
        }
        const ids = this._collectAppliedLoyaltyProgramIdsFromPosOrder(order);
        const nLines =
            typeof order.get_orderlines === "function"
                ? (order.get_orderlines() || []).length
                : (order.orderlines || []).length;
        console.info(
            "[OCA_PROMOS] sync lealtad → sesión | session_id=%s | líneas_carrito=%s | loyalty.program ids=%s",
            sid,
            nLines,
            JSON.stringify(ids)
        );
        await this.env.services.orm.silent
            .call("pos.session", "oca_promociones_set_cart_loyalty_programs", [
                [sid],
                ids,
            ])
            .then(() => {
                console.info(
                    "[OCA_PROMOS] oca_promociones_set_cart_loyalty_programs OK (revisar log servidor OCA_PROMOS_SESSION)"
                );
            })
            .catch((err) => {
                console.warn(
                    "[OCA promos] oca_promociones_set_cart_loyalty_programs:",
                    err
                );
            });
    },

    /**
     * Extiende send_payment_request para agregar flag NeedToReadCard
     * 
     * IMPORTANTE: NO llamamos a super.send_payment_request() porque el backend
     * ya está agregando NeedToReadCard: True cuando hay promociones activas.
     * Solo implementamos la lógica necesaria aquí.
     */
    async send_payment_request(cid) {
        // NO llamar al método base para evitar doble envío
        // El backend ya maneja NeedToReadCard cuando hay promociones activas
        // Solo implementar la lógica de envío aquí
        return this._send_payment_with_promotions(cid);
    },

    /**
     * Método auxiliar para enviar pago con soporte de promociones
     * 
     * Este método reemplaza completamente la lógica de send_payment_request
     * para evitar doble envío. El backend ya maneja NeedToReadCard cuando hay promociones activas.
     * 
     * IMPORTANTE: Este método implementa toda la lógica de send_payment_request del método base
     * pero sin llamar a super.send_payment_request() para evitar doble envío.
     */
    async _send_payment_with_promotions(cid) {
        console.log('-----------------PaymentOCA_Promociones send_payment_request------------------');
        
        var order = this.pos.get_order();
        var line = order.selected_paymentline;
        var orderlines = order.get_orderlines();
        var has_refunded_line = false;
        var refunded_ids = [];

        orderlines.forEach(function (orderline) {
            if (orderline.refunded_orderline_id) {
                has_refunded_line = true;
                refunded_ids.push(orderline.refunded_orderline_id);
            }
        });

        if (line.amount <= 0 && !has_refunded_line) {
            this._show_error('El monto del pago debe ser mayor a 0.0');
            return Promise.resolve();
        }

        if (line.amount >= 0 && has_refunded_line) {
            this._show_error('El monto del pago debe ser menor a 0.0');
            return Promise.resolve();
        }

        if (!has_refunded_line) {
            await this._syncOcaCartLoyaltyProgramsToSession(order);
        }

        var total_order_amount = Math.round(Math.abs(order.get_total_with_tax()) * 100);
        var total_order_amount_without_tax = Math.round(Math.abs(order.get_total_without_tax()) * 100);
        var amount_to_send_by_100 = Math.round(Math.abs(line.amount) * 100);
        var amount_to_send_float = Math.abs(line.amount);

        var currency = this.pos.currency.name;
        var currency_code = currency === "USD" ? "840" : "858";

        // Respetar siempre el nro de cuotas elegido en el POS (line.installments).
        // Si no está definido o es inválido, usar 1 para compatibilidad con OCA.
        var numCuotas = this._getInstallmentsFromPaymentLine(line);

        var data = this.get_base_data();
        data.Amount = `${amount_to_send_by_100}`;
        data.Quotas = "0";
        data.Plan = "0";
        data.Currency = currency_code;
        data.TaxRefund = "99";
        data.TaxableAmount = `${total_order_amount_without_tax}`;
        data.InvoiceAmount = `${total_order_amount}`;
        data.InvoiceNumber = "1";
        data.Installments = `${numCuotas}`;
        data.TicketNumber = "";

        const loyaltyIdsForPayload =
            this._collectAppliedLoyaltyProgramIdsFromPosOrder(order);
        if (loyaltyIdsForPayload.length && !has_refunded_line) {
            data.OcaAppliedLoyaltyProgramIds = loyaltyIdsForPayload.join(",");
            console.info(
                "[OCA_PROMOS] payload enviar_pago incluye OcaAppliedLoyaltyProgramIds=%s (si el conector lo conserva)",
                data.OcaAppliedLoyaltyProgramIds
            );
        } else {
            console.info(
                "[OCA_PROMOS] sin OcaAppliedLoyaltyProgramIds en payload (vacío o reembolso) | reembolso=%s",
                has_refunded_line
            );
        }

        // NO agregar NeedToReadCard aquí porque el backend ya lo agrega
        // cuando hay promociones activas configuradas
        // El backend verifica si hay promociones y agrega NeedToReadCard: True automáticamente

        console.log('OCA Payment Data (backend agregará NeedToReadCard si hay promociones):', JSON.stringify(data, null, 2));

        if (has_refunded_line) {
            var odoo_backend_response = await this.env.services.orm.silent.call(
                "pos.payment.method",
                "get_ticket_number",
                [[this.payment_method.id], refunded_ids, amount_to_send_float]
            ).catch(this.handle_odoo_connection_failure.bind(this));

            if (!odoo_backend_response.TicketNumber) {
                this._show_error('No se encontró número de ticket para reembolsar');
                return Promise.resolve();
            }
            data = this.get_base_data();
            data.TicketNumber = odoo_backend_response.TicketNumber;
            data.Acquirer = odoo_backend_response.Acquirer;
            // NO agregar NeedToReadCard aquí, el backend lo maneja
        }

        return this.enviar_pago(data, has_refunded_line).then((data) => {
            return this.handle_response_enviar_pago(data);
        });
    },

    /**
     * Extiende handleOCAStatusResponse para detectar ResponseCode = 12 con datos de tarjeta
     */
    async handleOCAStatusResponse(payload) {
        console.log("handleOCAStatusResponse - Promociones");
        const line = this.pending_oca_line();
        if (line.cancelled) {
            return;
        }

        var array_of_correct_codes = ['00', '08', '10', '11', '85'];
        var response_code = payload.ResponseCode;
        var pos_response_code = payload.PosResponseCode;
        var isPaymentSuccessful = false;

        // Cobro cancelado en servidor: promo OCA incompatible con lealtad del carrito (reversión enviada)
        if (
            payload.promotion_incompatible_cancelled ||
            String(response_code) === "999"
        ) {
            const msg =
                payload.msg ||
                "El pago no puede completarse: la promoción de tarjeta es incompatible con beneficios del pedido.";
            this._show_error(msg);
            const resolver = this.paymentLineResolvers?.[line.cid];
            if (resolver) {
                resolver(false);
            } else {
                line.handle_payment_response(false);
            }
            return;
        }

        // NUEVO: Detectar ResponseCode = 12 con datos de tarjeta (promociones)
        // Nota: CardNumber puede no estar presente en todas las respuestas, solo Acquirer e Issuer son suficientes
        if (response_code === '12' && payload.Acquirer && payload.Acquirer !== 0 && payload.Issuer && payload.Issuer !== 0) {
            console.log('Datos de tarjeta recibidos - Acquirer:', payload.Acquirer, 'Issuer:', payload.Issuer, 'CardNumber:', payload.CardNumber);
            // Tenemos datos de la tarjeta, procesar promoción
            // Solo procesar una vez, no en cada polling
            if (!line.promotion_processed) {
                line.promotion_processed = true;
                return this.processPromotionAndConfirm(payload, line);
            } else {
                // Ya se procesó la promoción, solo esperar confirmación
                console.log('Promoción ya procesada, esperando confirmación...');
                return;
            }
        }

        if (response_code === '0') {
            if (pos_response_code && array_of_correct_codes.includes(pos_response_code)) {
                isPaymentSuccessful = true;
            }
        }

        if (isPaymentSuccessful) {
            line.transaction_id = payload.origin_transaction_id;
            line.card_type = payload.Acquirer;
            line.ticket = payload.Ticket;
            line.cardholder_name = payload.CardOwnerName;
        } else {
            // Construir mensaje de error más descriptivo
            var msg_error = '';
            
            if (payload.timeout_error || response_code === '11') {
                msg_error = payload.msg || 'Tiempo de transacción excedido. Se procesó la reversión del pago.';
                if (payload.reverse_processed) {
                    if (payload.reverse_success) {
                        msg_error += ' La reversión fue exitosa. Puede intentar el pago nuevamente.';
                    } else {
                        msg_error += ' Hubo un problema con la reversión. Contacte al administrador.';
                    }
                }
            } else if (payload.msg) {
                msg_error = payload.msg;
                if (pos_response_code) {
                    msg_error += ` (Código POS: ${pos_response_code})`;
                }
            } else if (pos_response_code) {
                msg_error = `Error POS RESPONSE CODE: ${pos_response_code}`;
            } else {
                msg_error = `Error en el pago. ResponseCode: ${response_code}`;
            }
            
            this._show_error(msg_error);
        }

        const resolver = this.paymentLineResolvers?.[line.cid];
        if (resolver) {
            resolver(isPaymentSuccessful);
        } else {
            line.handle_payment_response(isPaymentSuccessful);
        }
    },

    /**
     * Procesa la promoción basada en datos de la tarjeta y confirma la transacción
     */
    async processPromotionAndConfirm(cardData, paymentLine) {
        const self = this;
        const order = this.pos.get_order();
        
        try {
            console.log('Procesando promoción con datos:', cardData);
            
            // 1. Obtener información de promoción del backend
            const serverOrderId = this._getServerPosOrderId(order);
            const appliedLoyaltyIds =
                this._collectAppliedLoyaltyProgramIdsFromPosOrder(order);
            console.info(
                "[OCA_PROMOS] processPromotionAndConfirm | get_promotion_info con appliedLoyaltyIds=%s | serverOrderId=%s",
                JSON.stringify(appliedLoyaltyIds),
                serverOrderId
            );
            const promotionInfo = await this.getPromotionInfo(
                cardData,
                order.pos_session_id,
                serverOrderId,
                appliedLoyaltyIds
            );

            if (promotionInfo.blockedByIncompatibility) {
                const msg =
                    promotionInfo.userMessage ||
                    "Este pago no puede continuar: promoción de tarjeta incompatible con el pedido.";
                this._show_error(msg);
                paymentLine.set_payment_status("force_done");
                const resolver = this.paymentLineResolvers?.[paymentLine.cid];
                if (resolver) {
                    resolver(false);
                } else {
                    paymentLine.handle_payment_response(false);
                }
                return;
            }

            if (promotionInfo.hasPromotion && promotionInfo.discountAmount > 0) {
                console.log('Promoción aplicable - Descuento:', promotionInfo.discountAmount);
                
                // 2. Agregar línea de descuento a la orden en el backend
                const discountResult = await this.addDiscountLineToOrder(
                    serverOrderId || order.id,
                    promotionInfo.discountAmount,
                    promotionInfo.productId,
                    promotionInfo.description || "Descuento Promoción",
                    promotionInfo.promotionId || false
                );
                
                if (!discountResult.success) {
                    console.error("Error al agregar línea de descuento:", discountResult.error);
                    if (discountResult.incompatible_promotion) {
                        this._show_error(
                            discountResult.error ||
                                "Promoción de tarjeta incompatible con el pedido."
                        );
                        paymentLine.set_payment_status("force_done");
                        const resolverFail = this.paymentLineResolvers?.[paymentLine.cid];
                        if (resolverFail) {
                            resolverFail(false);
                        } else {
                            paymentLine.handle_payment_response(false);
                        }
                        return;
                    }
                    return this.confirmFinancialPurchaseWithoutPromotion(cardData, paymentLine);
                }
                
                // 3. Obtener nuevo monto total de la orden (desde backend)
                const orderData = await this.getOrderUpdatedTotals(serverOrderId || order.id);

                // 3b. Actualizar el monto de la línea de pago al total con descuento aplicado.
                //     Usar set_amount() para que el POS actualice redondeo y estado interno.
                //     Así el pos.payment que se cree tendrá el importe correcto (con promoción).
                //     Al probar: en consola del navegador debe verse el log con montos antes/después.
                const amountBefore = paymentLine.get_amount ? paymentLine.get_amount() : paymentLine.amount;
                const newTotal = orderData.newTotal != null ? orderData.newTotal : orderData.newInvoiceAmount;
                const amountWithDiscount = Math.abs(newTotal);
                if (typeof paymentLine.set_amount === 'function') {
                    paymentLine.set_amount(amountWithDiscount);
                } else {
                    paymentLine.amount = amountWithDiscount;
                }
                const amountAfter = paymentLine.get_amount ? paymentLine.get_amount() : paymentLine.amount;
                console.log(
                    '[OCA Promociones] Monto de línea de pago actualizado para que pos.payment quede correcto:',
                    'antes=', amountBefore,
                    'después (con descuento)=', amountAfter,
                    'newTotal=', newTotal
                );

                // 4. Preparar datos para confirmación con nuevo monto
                const confirmData = this.prepareConfirmData(
                    cardData,
                    paymentLine,
                    orderData.newTotal,
                    orderData.newTaxableAmount,
                    orderData.newInvoiceAmount
                );
                
                // 5. Llamar a processConfirmFinancialPurchase
                const confirmResponse = await this.confirmFinancialPurchase(confirmData);
                
                // 6. Continuar esperando respuesta final
                if (confirmResponse.ResponseCode === '10' || confirmResponse.ResponseCode === '0') {
                    // Continuar con el flujo normal de espera
                    return this.waitForPaymentConfirmation();
                } else {
                    // Error en confirmación
                    this._show_error(`Error al confirmar transacción: ${confirmResponse.msg || confirmResponse.ResponseCode}`);
                    paymentLine.set_payment_status('force_done');
                    return Promise.resolve();
                }
            } else {
                // No hay promoción, confirmar con valores originales
                console.log('No hay promoción aplicable');
                return this.confirmFinancialPurchaseWithoutPromotion(cardData, paymentLine);
            }
        } catch (error) {
            console.error('Error en processPromotionAndConfirm:', error);
            this._show_error('Error al procesar promoción. Continuando sin descuento.');
            // Continuar sin promoción
            return this.confirmFinancialPurchaseWithoutPromotion(cardData, paymentLine);
        }
    },

    /**
     * Obtiene información de promoción basada en datos de la tarjeta
     */
    async getPromotionInfo(
        cardData,
        sessionId,
        posOrderId = false,
        appliedLoyaltyProgramIds = null
    ) {
        return this.env.services.orm.silent
            .call("pos.payment.method", "get_promotion_info", [
                [this.payment_method.id],
                cardData,
                sessionId,
                posOrderId || false,
                appliedLoyaltyProgramIds,
            ])
            .catch((error) => {
                console.error("Error al obtener información de promoción:", error);
                return {
                    hasPromotion: false,
                    discountAmount: 0,
                    productId: false,
                    description: "",
                    blockedByIncompatibility: false,
                    userMessage: "",
                    promotionId: false,
                };
            });
    },

    /**
     * Agrega una línea de descuento a la orden POS
     */
    async addDiscountLineToOrder(
        orderId,
        discountAmount,
        productId,
        description,
        promotionId = false
    ) {
        return this.env.services.orm.silent.call(
            "pos.order",
            "add_promotion_discount_line",
            [[orderId], discountAmount, productId, description, promotionId]
        ).catch((error) => {
            console.error('Error al agregar línea de descuento:', error);
            return {
                success: false,
                error: error.message || 'Error desconocido'
            };
        });
    },

    /**
     * Obtiene los totales actualizados de la orden después de agregar descuento
     */
    async getOrderUpdatedTotals(orderId) {
        return this.env.services.orm.silent.call(
            "pos.order",
            "get_order_totals",
            [[orderId]]
        ).catch((error) => {
            console.error('Error al obtener totales de orden:', error);
            // Retornar valores por defecto
            const order = this.pos.get_order();
            return {
                newTotal: order.get_total_with_tax(),
                newTaxableAmount: order.get_total_without_tax(),
                newInvoiceAmount: order.get_total_with_tax()
            };
        });
    },

    /**
     * Prepara los datos para confirmar la transacción con valores finales.
     * NOTA: En promociones NO enviamos la cantidad de cuotas al POS;
     * las cuotas se eligen y manejan en el pinpad físico.
     */
    prepareConfirmData(cardData, paymentLine, newTotal, newTaxableAmount, newInvoiceAmount) {
        const order = this.pos.get_order();
        const currency = this.pos.currency.name;
        const currency_code = currency === "USD" ? "840" : "858";
        
        // Convertir montos a centavos
        const amount_in_cents = Math.round(Math.abs(newTotal) * 100);
        const taxable_amount_in_cents = Math.round(Math.abs(newTaxableAmount) * 100);
        const invoice_amount_in_cents = Math.round(Math.abs(newInvoiceAmount) * 100);
        
        const data = this.get_base_data();
        data.TransactionId = paymentLine.transaction_id;
        data.Amount = `${amount_in_cents}`;
        data.Plan = "0";
        data.Currency = currency_code;
        data.TaxableAmount = `${taxable_amount_in_cents}`;
        data.InvoiceAmount = `${invoice_amount_in_cents}`;
        data.InvoiceNumber = order.name || "1";
        
        return data;
    },

    /**
     * Confirma la transacción financiera con valores modificados
     */
    async confirmFinancialPurchase(data) {
        const order = this.pos.get_order();
        const pos_session_id = order.pos_session_id;
        
        return this.env.services.orm.silent.call(
            "pos.payment.method",
            "processConfirmFinancialPurchase",
            [[this.payment_method.id], data, pos_session_id]
        ).catch(this.handle_odoo_connection_failure.bind(this));
    },

    /**
     * Confirma la transacción sin aplicar promoción (valores originales).
     * NOTA: En promociones NO enviamos la cantidad de cuotas al POS;
     * las cuotas se eligen y manejan en el pinpad físico.
     */
    async confirmFinancialPurchaseWithoutPromotion(cardData, paymentLine) {
        const order = this.pos.get_order();
        const currency = this.pos.currency.name;
        const currency_code = currency === "USD" ? "840" : "858";
        
        const total_order_amount = Math.round(Math.abs(order.get_total_with_tax()) * 100);
        const total_order_amount_without_tax = Math.round(Math.abs(order.get_total_without_tax()) * 100);
        
        const data = this.get_base_data();
        data.TransactionId = paymentLine.transaction_id;
        data.Amount = `${total_order_amount}`;
        data.Plan = "0";
        data.Currency = currency_code;
        data.TaxableAmount = `${total_order_amount_without_tax}`;
        data.InvoiceAmount = `${total_order_amount}`;
        data.InvoiceNumber = order.name || "1";
        
        const confirmResponse = await this.confirmFinancialPurchase(data);
        
        if (confirmResponse.ResponseCode === '10' || confirmResponse.ResponseCode === '0') {
            return this.waitForPaymentConfirmation();
        } else {
            this._show_error(`Error al confirmar transacción: ${confirmResponse.msg || confirmResponse.ResponseCode}`);
            paymentLine.set_payment_status('force_done');
            return Promise.resolve();
        }
    },
});

