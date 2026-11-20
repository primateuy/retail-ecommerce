/** @odoo-module */

// Una orden con un cobro OCA en curso o aprobado no se puede modificar (Forum, 2026-11-20).
// Validación, Shop/1411: la caja se recargó con el pinpad esperando un cobro de 3.000, la orden
// se bajó a 1.800 y el cobro aprobado terminó con 1.200 de vuelto en efectivo.
//
// Sin dependencias a propósito: se prueba con node (tests/js/test_oca_bloqueo.mjs).

// Estados de la línea con el pinpad trabajando: el cobro todavía puede aprobarse.
export const OCA_ESTADOS_EN_CURSO = ["waiting", "waitingCard", "waitingCancel", "timeout"];

function estadoDe(line) {
    return typeof line.get_payment_status === "function"
        ? line.get_payment_status()
        : line.payment_status;
}

/** La línea es de OCA y su cobro está en curso o aprobado (sin revertir). */
export function ocaLineaBloqueaOrden(line) {
    if (!line || line.payment_method?.use_payment_terminal !== "oca") {
        return false;
    }
    const estado = estadoDe(line);
    return OCA_ESTADOS_EN_CURSO.includes(estado) || estado === "done";
}

/** La orden no se puede modificar: tiene un cobro OCA en curso o aprobado. Una orden ya
 * finalizada no entra: el núcleo ya no la deja modificar y sigue su propio camino. */
export function ocaOrdenBloqueada(order) {
    if (!order || order.finalized) {
        return false;
    }
    const lineas = typeof order.get_paymentlines === "function"
        ? order.get_paymentlines()
        : order.paymentlines || [];
    return lineas.some(ocaLineaBloqueaOrden);
}
