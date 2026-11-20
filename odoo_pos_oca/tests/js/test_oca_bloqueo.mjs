// Tests de la regla «una orden con cobro OCA en curso o aprobado no se modifica».
//     node odoo_pos_oca/tests/js/test_oca_bloqueo.mjs
// Corre sin Odoo: oca_bloqueo.js no tiene dependencias.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";

const fuente = readFileSync(new URL("../../static/src/app/oca_bloqueo.js", import.meta.url), "utf8");
const {ocaLineaBloqueaOrden, ocaOrdenBloqueada} = await import(
    "data:text/javascript;base64," + Buffer.from(fuente).toString("base64")
);

const linea = (estado, terminal = "oca") => ({
    payment_method: {use_payment_terminal: terminal},
    get_payment_status: () => estado,
});
const orden = (lineas, finalized = false) => ({finalized, get_paymentlines: () => lineas});

test("cobro OCA esperando el pinpad bloquea la orden (recarga de Shop/1411)", () => {
    for (const estado of ["waiting", "waitingCard", "waitingCancel", "timeout"]) {
        assert.equal(ocaOrdenBloqueada(orden([linea(estado)])), true, estado);
    }
});

test("cobro OCA aprobado bloquea la orden", () => {
    assert.equal(ocaOrdenBloqueada(orden([linea("done")])), true);
});

test("rechazado, revertido o sin enviar no bloquea", () => {
    for (const estado of ["retry", "reversed", "pending", undefined]) {
        assert.equal(ocaOrdenBloqueada(orden([linea(estado)])), false, String(estado));
    }
});

test("otros medios de pago no bloquean", () => {
    assert.equal(ocaOrdenBloqueada(orden([linea("done", "fiserv"), linea("done", false)])), false);
});

test("orden ya finalizada no se bloquea (sigue el camino del núcleo)", () => {
    assert.equal(ocaOrdenBloqueada(orden([linea("done")], true)), false);
});

test("dos tarjetas: con una aprobada la orden queda bloqueada", () => {
    assert.equal(ocaOrdenBloqueada(orden([linea("done"), linea("retry")])), true);
});

test("sin orden o sin líneas no bloquea", () => {
    assert.equal(ocaOrdenBloqueada(null), false);
    assert.equal(ocaOrdenBloqueada(orden([])), false);
    assert.equal(ocaLineaBloqueaOrden(null), false);
});

test("línea con payment_status como propiedad (sin método)", () => {
    const l = {payment_method: {use_payment_terminal: "oca"}, payment_status: "waitingCard"};
    assert.equal(ocaOrdenBloqueada({paymentlines: [l]}), true);
});
