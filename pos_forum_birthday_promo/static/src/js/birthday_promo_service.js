/** @odoo-module **/

import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";
import { random5Chars } from "@point_of_sale/utils";
import { roundPrecision as round_pr } from "@web/core/utils/numbers";

/**
 * Retorna el importe de la línea a usar como base del % de descuento cumpleaños.
 *
 * Usa el total con impuestos incluidos (`get_price_with_tax`) para alinear el
 * descuento con TPV configurado en precios con impuestos incluidos. Si el método
 * no existiera (extensiones antiguas), cae en `get_price_without_tax`.
 *
 * @param {import("@point_of_sale/app/store/models").Orderline} line
 * @returns {number}
 */
function forumBirthdayLinePromoBaseAmount(line) {
    if (typeof line.get_price_with_tax === "function") {
        return line.get_price_with_tax();
    }
    return line.get_price_without_tax();
}

/**
 * Extiende el pedido POS para la promoción de cumpleaños Forum.
 *
 * - Considera `birthdate_date` (OCA) y `birthdate` (p. ej. Cybrosys): basta
 *   con que exista una fecha; el RPC decide si alguna entra en la ventana.
 * - Añade una línea de producto con descuento (no rebaja líneas sueltas).
 * - Marca la línea con `reward_id` de lealtad y `forum_birthday_line` para no
 *   ser eliminada por `_updateRewardLines` del motor estándar.
 */
patch(Order.prototype, {
    /**
     * Excluye las líneas de cumpleaños Forum del refresco automático de recompensas.
     *
     * También excluye por `reward_id` técnico para pedidos rehidratados desde servidor.
     */
    _get_reward_lines() {
        const lines = super._get_reward_lines(...arguments);
        const forumRewardId = this.pos?.config?.forum_birthday_reward_id?.[0];
        return lines.filter((line) => {
            if (line.forum_birthday_line) {
                return false;
            }
            if (forumRewardId && line.reward_id === forumRewardId) {
                return false;
            }
            return true;
        });
    },

    /**
     * Propaga la marca de línea técnica desde las opciones de `add_product`.
     */
    set_orderline_options(line, options) {
        super.set_orderline_options(...arguments);
        if (options && options.forum_birthday_line) {
            line.forum_birthday_line = true;
        }
    },

    /**
     * Evita reentrar en el motor de lealtad mientras se inserta la línea de cumpleaños.
     *
     * Si no hay programas de lealtad cargados, el estándar no llama a
     * `_updateRewardLines`; en ese caso programamos la sync aquí.
     */
    async _updateRewards() {
        if (this._forumBirthdaySuppressLoyaltyRewards) {
            return;
        }
        const willRunRewardLines = this.pos.programs.length > 0;
        const ret = super._updateRewards(...arguments);
        await Promise.resolve(ret);
        if (!willRunRewardLines) {
            this._forumBirthdayScheduleSync();
        }
    },

    /**
     * Tras sincronizar recompensas estándar, reprograma el cálculo de la promo cumpleaños.
     */
    _updateRewardLines() {
        super._updateRewardLines(...arguments);
        this._forumBirthdayScheduleSync();
    },

    /**
     * Al cambiar el cliente se recalcula si corresponde la línea de descuento.
     */
    set_partner(partner) {
        super.set_partner(...arguments);
        this._forumBirthdayScheduleSync();
    },

    /**
     * Agrupa llamadas al sincronizador para no disparar demasiados RPC seguidos.
     *
     * Retardo de 250 ms para ejecutar después de hooks de otros módulos (p. ej.
     * `pos_forum_loyalty_customer_domain` dispara lógica a los 150 ms al cambiar
     * cliente) y evitar que la línea de cumpleaños se pierda o quede incoherente.
     */
    _forumBirthdayScheduleSync() {
        const cfg = this.pos?.config;
        if (!cfg?.forum_birthday_promo_active) {
            return;
        }
        console.log("[bday] scheduleSync called, running=", this._forumBirthdaySyncRunning, "cooldown=", !!this._forumBirthdaySyncCooldown, "hasTimer=", !!this._forumBirthdaySyncTimer, new Error().stack.split("\n")[2]);
        if (this._forumBirthdaySyncRunning || this._forumBirthdaySyncCooldown) {
            console.log("[bday] scheduleSync BLOCKED by running/cooldown flag");
            return;
        }
        if (this._forumBirthdaySyncTimer) {
            clearTimeout(this._forumBirthdaySyncTimer);
        }
        this._forumBirthdaySyncTimer = setTimeout(() => {
            this._forumBirthdaySyncTimer = null;
            void this._forumBirthdaySyncExecute();
        }, 250);
    },

    /**
     * Quita líneas previas de la promo, valida con servidor y añade la línea de descuento.
     */
    async _forumBirthdaySyncExecute() {
        const cfg = this.pos?.config;
        console.log("[bday] execute called, running=", this._forumBirthdaySyncRunning);
        if (!cfg?.forum_birthday_promo_active || this._forumBirthdaySyncRunning) {
            console.log("[bday] execute ABORTED active=", cfg?.forum_birthday_promo_active, "running=", this._forumBirthdaySyncRunning);
            return;
        }
        this._forumBirthdaySyncRunning = true;
        // Preserve the cashier's current selection so the sync doesn't hijack it.
        const savedSelectedLine = this.selected_orderline;
        try {
            const forumRewardId = cfg.forum_birthday_reward_id?.[0];
            for (const line of [...this.get_orderlines()]) {
                const isForumLine =
                    line.forum_birthday_line ||
                    (forumRewardId && line.reward_id === forumRewardId);
                if (isForumLine) {
                    console.log("[bday] removing old birthday line");
                    this._unlinkOrderline(line);
                }
            }
            const partner = this.get_partner();
            const hasBirthRef =
                partner && (partner.birthdate_date || partner.birthdate);
            if (!hasBirthRef) {
                console.log("[bday] no birthdate, exit");
                return;
            }
            const productId = cfg.forum_birthday_product_id?.[0];
            const product = productId ? this.pos.db.get_product_by_id(productId) : null;
            if (!product) {
                console.log("[bday] no product, exit");
                return;
            }
            const rewardId = cfg.forum_birthday_reward_id?.[0];
            if (!rewardId) {
                console.log("[bday] no rewardId, exit");
                return;
            }
            const orm = this.pos.env.services.orm;
            console.log("[bday] calling eligibility RPC");
            const elig = await orm.call("pos.session", "forum_birthday_check_eligibility", [
                [this.pos.pos_session.id],
                partner.id,
            ]);
            console.log("[bday] eligibility result=", elig, "running=", this._forumBirthdaySyncRunning);
            if (!elig?.eligible) {
                return;
            }
            const percent = cfg.forum_birthday_discount_percent || 0;
            if (percent <= 0) {
                return;
            }
            let base = 0;
            for (const line of this.get_orderlines()) {
                if (line.is_reward_line || line.refunded_orderline_id || line.forum_birthday_line) {
                    continue;
                }
                base += forumBirthdayLinePromoBaseAmount(line);
            }
            base = round_pr(base, this.pos.currency.rounding);
            console.log("[bday] base=", base, "percent=", percent);
            if (base <= 0) {
                return;
            }
            const discountAmount = round_pr((base * percent) / 100.0, this.pos.currency.rounding);
            if (discountAmount <= 0) {
                return;
            }
            console.log("[bday] adding line discountAmount=", discountAmount);
            this._forumBirthdaySuppressLoyaltyRewards = true;
            try {
                await this.add_product(product, {
                    quantity: 1,
                    price: -discountAmount,
                    merge: false,
                    is_reward_line: false,
                    reward_id: rewardId,
                    reward_identifier_code: random5Chars(),
                    points_cost: 0,
                    forum_birthday_line: true,
                });
            } finally {
                this._forumBirthdaySuppressLoyaltyRewards = false;
            }
            console.log("[bday] line added, calling _updateRewards, running=", this._forumBirthdaySyncRunning);
            await this._updateRewards();
            console.log("[bday] _updateRewards done, running=", this._forumBirthdaySyncRunning);
            // Restore the cashier's selection — add_product selects the birthday
            // line, which would deselect whatever the cashier had chosen.
            if (savedSelectedLine && this.get_orderlines().includes(savedSelectedLine)) {
                this.select_orderline(savedSelectedLine);
            }
        } finally {
            console.log("[bday] execute FINALLY, setting running=false");
            this._forumBirthdaySyncRunning = false;
            // The reactive system (Owl) fires _updateRewardLines via microtasks
            // after the async function settles. All microtasks are guaranteed to
            // drain before the next macrotask (setTimeout), so holding this flag
            // true until setTimeout(0) fires absorbs the entire reactive burst
            // and prevents a new sync cycle.
            this._forumBirthdaySyncCooldown = true;
            setTimeout(() => {
                this._forumBirthdaySyncCooldown = false;
                console.log("[bday] cooldown cleared");
            }, 0);
        }
    },
});
