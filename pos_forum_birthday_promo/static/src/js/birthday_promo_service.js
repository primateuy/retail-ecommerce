/** @odoo-module **/

import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";
import { random5Chars } from "@point_of_sale/utils";
import { roundPrecision as round_pr } from "@web/core/utils/numbers";

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
     */
    _forumBirthdayScheduleSync() {
        const cfg = this.pos?.config;
        if (!cfg?.forum_birthday_promo_active) {
            return;
        }
        if (this._forumBirthdaySyncTimer) {
            clearTimeout(this._forumBirthdaySyncTimer);
        }
        this._forumBirthdaySyncTimer = setTimeout(() => {
            this._forumBirthdaySyncTimer = null;
            void this._forumBirthdaySyncExecute();
        }, 80);
    },

    /**
     * Quita líneas previas de la promo, valida con servidor y añade la línea de descuento.
     */
    async _forumBirthdaySyncExecute() {
        const cfg = this.pos?.config;
        if (!cfg?.forum_birthday_promo_active || this._forumBirthdaySyncRunning) {
            return;
        }
        this._forumBirthdaySyncRunning = true;
        try {
            const forumRewardId = cfg.forum_birthday_reward_id?.[0];
            for (const line of [...this.get_orderlines()]) {
                const isForumLine =
                    line.forum_birthday_line ||
                    (forumRewardId && line.reward_id === forumRewardId);
                if (isForumLine) {
                    this._unlinkOrderline(line);
                }
            }
            const partner = this.get_partner();
            const hasBirthRef =
                partner && (partner.birthdate_date || partner.birthdate);
            if (!hasBirthRef) {
                return;
            }
            const productId = cfg.forum_birthday_product_id?.[0];
            const product = productId ? this.pos.db.get_product_by_id(productId) : null;
            if (!product) {
                return;
            }
            const rewardId = cfg.forum_birthday_reward_id?.[0];
            if (!rewardId) {
                return;
            }
            const orm = this.pos.env.services.orm;
            const elig = await orm.call("pos.session", "forum_birthday_check_eligibility", [
                [this.pos.pos_session.id],
                partner.id,
            ]);
            if (!elig?.eligible) {
                return;
            }
            const percent = cfg.forum_birthday_discount_percent || 0;
            if (percent <= 0) {
                return;
            }
            let base = 0;
            for (const line of this.get_orderlines()) {
                if (line.is_reward_line || line.refunded_orderline_id) {
                    continue;
                }
                base += line.get_price_without_tax();
            }
            base = round_pr(base, this.pos.currency.rounding);
            if (base <= 0) {
                return;
            }
            const discountAmount = round_pr((base * percent) / 100.0, this.pos.currency.rounding);
            if (discountAmount <= 0) {
                return;
            }
            this._forumBirthdaySuppressLoyaltyRewards = true;
            try {
                await this.add_product(product, {
                    quantity: 1,
                    price: -discountAmount,
                    merge: false,
                    is_reward_line: true,
                    reward_id: rewardId,
                    reward_identifier_code: random5Chars(),
                    points_cost: 0,
                    forum_birthday_line: true,
                });
            } finally {
                this._forumBirthdaySuppressLoyaltyRewards = false;
            }
        } finally {
            this._forumBirthdaySyncRunning = false;
        }
    },
});
