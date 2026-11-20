// Puntos de lealtad en el ticket: impresión al cobrar y reimpresión (Forum, 2026-11-20).
//     node --test odoo_pos_no_invoice/tests/js/test_puntos_ticket.mjs
// Corre el getter templateProps de receipt_cfe_data.js con Owl y Odoo reemplazados por stubs.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";

const fuente = readFileSync(new URL("../../static/src/js/receipt_cfe_data.js", import.meta.url), "utf8")
    .replace(/^import .*$/gm, "");
const stubs = "const OrderReceipt={prototype:{}};const patch=(t,o)=>{globalThis.__parche=o;};" +
    "const useState=(x)=>x;const onMounted=()=>{};const useService=()=>({});\n";
await import("data:text/javascript;base64," + Buffer.from(stubs + fuente).toString("base64"));
const templateProps = Object.getOwnPropertyDescriptor(globalThis.__parche, "templateProps").get;

const DEL_SERVIDOR = {card_id: 795814, antes: 210, despues: 228, generados: 18, canjeados: 0,
    es_devolucion: false, partner_category_ids: []};
const EN_MEMORIA = [{points: {won: 18, spent: 0, balance: 228, total: 228}}];

function ticket({viva, finalizada, enMemoria = [], servidor = {}}) {
    const order = {name: viva, finalized: finalizada, get_partner: () => null,
        getLoyaltyPoints: () => enMemoria, _isRefundOrMixedOrder: () => false,
        get_orderlines: () => [], paymentlines: []};
    const ctx = {
        pos: {get_order: () => order, config: {name: "Shop"}, currency: {name: "UYU"}},
        state: {cfeData: {}, receiptData: null, ocaVoucher: {}, ocaVouchers: [], deductedPoints: []},
        props: {data: {name: "Orden 03256-001-0001", orderlines: [], paymentlines: [],
            _skipAsyncReload: true, legal_data: {}, adenda_data: {}, reprint_loyalty: servidor}},
        env: {services: {}},
    };
    const log = console.log;
    console.log = () => {};
    try {
        return templateProps.call(ctx).data;
    } finally {
        console.log = log;
    }
}

function puntos(data) {
    const p = data.loyaltyStats[0]?.points;
    return p && [p.balance - p.won, p.won, data.loyalty_current_balance];
}

test("reimprime con otra venta abierta en la caja", () => {
    const d = ticket({viva: "Orden 03256-001-0002", finalizada: false, servidor: DEL_SERVIDOR});
    assert.equal(d.loyalty_visible, true);
    assert.deepEqual(puntos(d), [210, 18, 228]);
});

test("reimprime la misma venta ya cobrada (validación, Shop/1417)", () => {
    const d = ticket({viva: "Orden 03256-001-0001", finalizada: true, servidor: DEL_SERVIDOR});
    assert.equal(d.loyalty_visible, true);
    assert.deepEqual(puntos(d), [210, 18, 228]);
});

test("imprime al cobrar: da lo mismo con o sin datos del servidor", () => {
    const con = ticket({viva: "Orden 03256-001-0001", finalizada: true, enMemoria: EN_MEMORIA, servidor: DEL_SERVIDOR});
    const sin = ticket({viva: "Orden 03256-001-0001", finalizada: true, enMemoria: EN_MEMORIA});
    assert.deepEqual(puntos(con), [210, 18, 228]);
    assert.deepEqual(puntos(sin), puntos(con));
});

test("reimprime una venta sin puntos: no muestra los de la venta en curso", () => {
    const d = ticket({viva: "Orden 03256-001-0002", finalizada: false, enMemoria: EN_MEMORIA});
    assert.equal(d.loyalty_visible, false);
});

test("devolución reimpresa: puntos perdidos y saldo nuevo", () => {
    const d = ticket({viva: "Orden 03256-001-0002", finalizada: false,
        servidor: {...DEL_SERVIDOR, antes: 228, despues: 210, generados: -18, es_devolucion: true}});
    assert.equal(d.loyalty_visible, true);
    assert.equal(d.loyalty_is_refund, true);
    assert.equal(d.points_lost, 18);
    assert.equal(d.loyalty_current_balance, 210);
});
