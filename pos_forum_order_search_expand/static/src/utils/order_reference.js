/** @odoo-module */

import { _t } from "@web/core/l10n/translation";

// Formato del nº de orden del POS (Order.generate_unique_id de point_of_sale):
//   zero_pad(pos_session.id, 5) "-" zero_pad(login_number, 3) "-" zero_pad(sequence_number, 4)
// El separador se acepta como cualquier carácter no alfanumérico: la lectora del
// ticket de cambio está configurada con un layout de teclado distinto al del
// sistema y emite "'" (u otro signo) donde el Code128 trae un "-", así que lo
// que llega al input es 00697'001'0001 en lugar de 00697-001-0001.
// Los largos mínimos (5/3/4) son los del zero_pad y evitan falsos positivos con
// otros términos separados por signos, p. ej. la fecha 01/02/2024.
// Sólo se ancla al final: el botón Reembolso abre la pantalla de órdenes con el
// nombre del cliente ya cargado en el buscador y la lectora teclea el código a
// continuación ("Consumidor Final00697'001'0001"), así que el nº de orden puede
// venir precedido por cualquier texto. Lo que importa es que termine con él.
const SCANNED_REFERENCE_RE = /(\d{5,})[^0-9A-Za-z](\d{3,})[^0-9A-Za-z](\d{4,})$/;

/**
 * Devuelve la parte numérica del nº de orden, o null si el valor no lo es.
 *
 * Tolera texto previo (prefijo "Orden ", nombre de cliente precargado, etc.) y
 * cualquier separador no alfanumérico, así que reconoce "00697'001'0001"
 * (lectura cruda), "00697-001-0001", "Orden 00697-001-0001" (tecleado a mano
 * o ya normalizado) y "Consumidor Final00697'001'0001" (lectura sobre un
 * buscador que ya tenía texto).
 *
 * @param {string} value texto escaneado o tecleado.
 * @returns {string|null} "00697-001-0001", o null si no termina con un nº de orden.
 */
export function parseOrderReference(value) {
    const text = (value || "").trim();
    if (!text) {
        return null;
    }
    const match = text.match(SCANNED_REFERENCE_RE);
    if (!match) {
        return null;
    }
    const [, sessionPart, loginPart, sequencePart] = match;
    return `${sessionPart}-${loginPart}-${sequencePart}`;
}

/**
 * Convierte lo que escupe la lectora del ticket de cambio en la referencia real.
 *
 * "00697'001'0001" -> "Orden 00697-001-0001". El prefijo sale de _t("Order %s"),
 * el mismo string con el que el POS arma pos_reference, así que respeta el
 * idioma de la sesión en vez de hardcodear "Orden". Cualquier texto que
 * precediera al código (p. ej. el nombre del cliente precargado) se descarta.
 *
 * Es idempotente y todo lo que no termine con un nº de orden se devuelve
 * intacto, para no romper las búsquedas por cliente, fecha o texto libre.
 *
 * @param {string} value texto escaneado o tecleado en el buscador.
 * @returns {string} referencia completa, o el valor original.
 */
export function normalizeScannedOrderReference(value) {
    const text = (value || "").trim();
    const reference = parseOrderReference(text);
    return reference ? _t("Order %s", reference) : text;
}

/**
 * Deja el término de búsqueda listo para el dominio contra pos_reference.
 *
 * Sólo la parte numérica: el dominio se arma con ilike '%término%', así que
 * buscar sin el prefijo hace que el match no dependa del idioma con el que el
 * PDV generó pos_reference. Si el término no es un nº de orden va tal cual.
 *
 * @param {string} value término de búsqueda.
 * @returns {string} término a usar en el dominio.
 */
export function formatOrderReferenceSearch(value) {
    const text = (value || "").trim();
    return parseOrderReference(text) || text;
}
