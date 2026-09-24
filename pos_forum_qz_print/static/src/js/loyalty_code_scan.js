/** @odoo-module */

import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

// Forma del código de cupón generado por loyalty.card._generate_code:
//   '044' + uuid4[7:-18]  ->  "044b-a0a0-44b5" (3 grupos de 4 hex separados por "-").
// La lectora del cupón de próxima compra tiene el mismo layout de teclado que la
// del ticket de cambio (ver pos_forum_order_search_expand/utils/order_reference.js)
// y emite "'" donde el Code128 trae "-", así que llega "044b'a0a0'44b5" y
// use_coupon_code (igualdad exacta contra loyalty.card.code) no lo encuentra.
// Se acepta cualquier separador no alfanumérico por si cambia el layout.
const SCANNED_COUPON_CODE_RE = /^([0-9a-f]{4})[^0-9a-z]([0-9a-f]{4})[^0-9a-z]([0-9a-f]{4})$/i;

// Apóstrofes que puede emitir el teclado (recto y tipográficos). Para códigos
// que no tienen la forma generada (promos manuales tipo "PROMO-10") alcanza
// con volver a poner el guion que la lectora reemplazó.
const APOSTROPHES_RE = /['‘’´`]/g;

/**
 * Devuelve el código del cupón tal como está guardado en loyalty.card.
 *
 * "044b'a0a0'44b5" -> "044b-a0a0-44b5". Es idempotente: un código ya correcto
 * o tecleado a mano se devuelve igual.
 *
 * @param {string} code lo que emitió la lectora o tecleó el cajero.
 * @returns {string} código con guiones.
 */
export function normalizeScannedCouponCode(code) {
    const text = (code || "").trim();
    const match = text.match(SCANNED_COUPON_CODE_RE);
    if (match) {
        return `${match[1]}-${match[2]}-${match[3]}`;
    }
    return text.replace(APOSTROPHES_RE, "-");
}

patch(Order.prototype, {
    /**
     * Normaliza el código antes de activarlo.
     *
     * Cubre las dos entradas del cupón: el escaneo en la pantalla de productos
     * (barcode_service -> regla "coupon" 043|044 -> _onCouponScan) y el popup
     * "Introducir código" del botón de promociones.
     */
    async activateCode(code) {
        return super.activateCode(normalizeScannedCouponCode(code));
    },
});
