/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Order } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { RewardButton } from "@pos_loyalty/app/control_buttons/reward_button/reward_button";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";

/**
 * Convierte valores del POS a lista de ids enteros (Many2many / varios formatos).
 *
 * En ``res.partner``, ``category_id`` (etiquetas) es M2M: puede venir como
 * ``[1, 2]``, ``[[1, "Nombre"], ...]`` o vacío.
 */
function toIdList(value) {
    if (value === false || value === undefined || value === null) {
        return [];
    }
    if (typeof value === "number") {
        return [value];
    }
    if (!Array.isArray(value)) {
        return [];
    }
    if (value.length === 0) {
        return [];
    }
    if (Array.isArray(value[0])) {
        return value.map((x) => x[0]).filter((x) => typeof x === "number");
    }
    if (
        value.length === 2 &&
        typeof value[0] === "number" &&
        (typeof value[1] === "string" || value[1] === false)
    ) {
        return [value[0]];
    }
    if (value.every((x) => typeof x === "number")) {
        return value;
    }
    return [];
}

/**
 * Un solo id (lado derecho del dominio o comparación Many2one).
 */
function toSingleId(value) {
    if (typeof value === "number") {
        return value;
    }
    if (Array.isArray(value) && value.length && typeof value[0] === "number") {
        return value[0];
    }
    return value;
}

/**
 * Valor crudo del partner para una hoja de dominio (sin normalizar M2one/M2M).
 */
function getLeafFieldValue(record, fieldName) {
    return record?.[fieldName];
}

/**
 * Evalúa operadores de dominio sobre un registro partner cargado en el POS.
 *
 * Soporta ``category_id`` (M2M / etiquetas) con ``in``, ``not in`` y ``=``.
 * Dominios mal formados se tratan como permitir para no bloquear el cajero.
 */
function compareValues(left, operator, right) {
    const leftIds = toIdList(left);

    switch (operator) {
        case "=": {
            const rid = toSingleId(right);
            if (leftIds.length) {
                return leftIds.includes(rid);
            }
            if (Array.isArray(left) && left.length === 2 && typeof left[0] === "number") {
                return left[0] === rid;
            }
            return left === right;
        }
        case "!=": {
            return !compareValues(left, "=", right);
        }
        case "in": {
            const allowed = (Array.isArray(right) ? right : []).map(toSingleId);
            if (leftIds.length) {
                return leftIds.some((id) => allowed.includes(id));
            }
            if (Array.isArray(left) && left.length === 2 && typeof left[0] === "number") {
                return allowed.includes(left[0]);
            }
            return allowed.includes(left);
        }
        case "not in": {
            return !compareValues(left, "in", right);
        }
        case ">":
            return left > right;
        case ">=":
            return left >= right;
        case "<":
            return left < right;
        case "<=":
            return left <= right;
        case "ilike": {
            const lt = String(left || "").toLowerCase();
            const rt = String(right || "").toLowerCase();
            return lt.includes(rt);
        }
        case "like":
            return String(left || "").includes(String(right || ""));
        case "=?":
            return !right || compareValues(left, "=", right);
        default:
            return true;
    }
}

function evalDomainNode(record, node) {
    if (!Array.isArray(node)) {
        return true;
    }
    if (typeof node[0] === "string" && !["&", "|", "!"].includes(node[0]) && node.length === 3) {
        const [fieldName, operator, value] = node;
        return compareValues(getLeafFieldValue(record, fieldName), operator, value);
    }
    const token = node[0];
    if (token === "!") {
        return !evalDomainNode(record, node[1]);
    }
    if (token === "&") {
        return evalDomainNode(record, node[1]) && evalDomainNode(record, node[2]);
    }
    if (token === "|") {
        return evalDomainNode(record, node[1]) || evalDomainNode(record, node[2]);
    }
    return node.every((item) => evalDomainNode(record, item));
}

/**
 * Regla de lealtad: sin dominio de cliente o partner cumple el dominio JSON.
 */
function ruleMatchesPartnerCustomerDomain(partner, rule) {
    if (!rule.customer_domain || rule.customer_domain === "[]") {
        return true;
    }
    if (!partner) {
        return false;
    }
    try {
        const domain = JSON.parse(rule.customer_domain);
        return evalDomainNode(partner, domain);
    } catch {
        return true;
    }
}

/**
 * Programa con reglas que tienen dominio de cliente: el partner debe cumplir
 * al menos una de esas reglas (coherente con el uso típico en ventas).
 */
function programAppliesForPartner(pos, partner, programId) {
    const program = pos.program_by_id[programId];
    if (!program?.rules?.length) {
        return true;
    }
    const domainRules = program.rules.filter(
        (r) => r.customer_domain && r.customer_domain !== "[]"
    );
    if (!domainRules.length) {
        return true;
    }
    if (!partner) {
        return false;
    }
    return domainRules.some((rule) => ruleMatchesPartnerCustomerDomain(partner, rule));
}

function getProgramIdFromReward(reward) {
    if (!reward?.program_id) {
        return false;
    }
    if (typeof reward.program_id === "object" && reward.program_id.id) {
        return reward.program_id.id;
    }
    return Array.isArray(reward.program_id) ? reward.program_id[0] : reward.program_id;
}

function filterClaimableEntries(order, entries) {
    if (!Array.isArray(entries)) {
        return entries;
    }
    const partner = order.get_partner();
    const pos = order.pos;
    return entries.filter((item) =>
        programAppliesForPartner(pos, partner, getProgramIdFromReward(item.reward))
    );
}

/** Evita ráfagas de llamadas al reaplicar lista/precio al cambiar de cliente varias veces seguidas. */
let _forumLoyaltyPartnerDebounceTimer = null;

/**
 * Tras cambiar el cliente, vuelve a ejecutar el hook de otros módulos que aplican
 * ``pricelist_change`` / ``fixed_price`` (p. ej. ``_applyCustomRewardsOnly``), con el
 * mismo retardo que suelen usar al cambiar cantidades, para que al volver a un
 * partner elegible el dominio de lealtad y la lista promo sigan coherentes.
 */
function forumDebouncedApplyCustomRewardsAfterPartnerChange(order, delay = 150) {
    if (_forumLoyaltyPartnerDebounceTimer) {
        clearTimeout(_forumLoyaltyPartnerDebounceTimer);
    }
    _forumLoyaltyPartnerDebounceTimer = setTimeout(() => {
        _forumLoyaltyPartnerDebounceTimer = null;
        if (!order || order.finalized) {
            return;
        }
        if (typeof order._applyCustomRewardsOnly !== "function") {
            return;
        }
        try {
            order._applyCustomRewardsOnly();
        } catch (e) {
            console.error(
                "[pos_forum_loyalty_customer_domain] Error en _applyCustomRewardsOnly tras cambio de cliente:",
                e
            );
        }
    }, delay);
}

patch(Order.prototype, {
    /**
     * Si hay programas con lista o precio fijo custom y otro módulo aporta
     * ``_applyCustomRewardsOnly``, lo disparamos al cambiar cliente: sin esto, al
     * volver al contacto que cumple el dominio la orden puede quedar solo con la
     * lista del partner porque ese hook solo corría en ``set_quantity``.
     */
    set_partner(partner) {
        super.set_partner(...arguments);
        if (this.finalized) {
            return;
        }
        const programs = this.pos?.programs || [];
        const hasCustomPriceRewards = programs.some((p) =>
            p.rewards?.some(
                (r) =>
                    r.reward_type === "pricelist_change" ||
                    r.reward_type === "fixed_price"
            )
        );
        if (hasCustomPriceRewards) {
            forumDebouncedApplyCustomRewardsAfterPartnerChange(this, 150);
        }
    },

    /**
     * Oculta recompensas de programas cuyo dominio de cliente no cumple el partner.
     */
    getClaimableRewards() {
        const rewards = super.getClaimableRewards(...arguments);
        return filterClaimableEntries(this, rewards);
    },

    /**
     * Solo las reglas cuyo dominio de cliente satisface el partner aportan puntos.
     */
    pointsForPrograms(programs) {
        const partner = this.get_partner();
        const backup = new Map();
        for (const program of programs) {
            if (!program?.rules) {
                continue;
            }
            backup.set(program.id, program.rules);
            program.rules = program.rules.filter((rule) =>
                ruleMatchesPartnerCustomerDomain(partner, rule)
            );
        }
        try {
            return super.pointsForPrograms(...arguments);
        } finally {
            for (const program of programs) {
                if (backup.has(program.id)) {
                    program.rules = backup.get(program.id);
                }
            }
        }
    },
});

patch(PosStore.prototype, {
    /**
     * Filtra productos gratis potenciales según dominio de cliente del programa.
     */
    getPotentialFreeProductRewards() {
        const rewards = super.getPotentialFreeProductRewards(...arguments);
        const order = this.get_order();
        if (!order) {
            return rewards;
        }
        return filterClaimableEntries(order, rewards);
    },
});

patch(RewardButton.prototype, {
    /**
     * Evita aplicar manualmente una recompensa si el cliente no entra en el dominio.
     */
    async _applyReward(reward, coupon_id, potentialQty) {
        const order = this.pos.get_order();
        const partner = order?.get_partner();
        const programId = getProgramIdFromReward(reward);
        if (!programAppliesForPartner(this.pos, partner, programId)) {
            this.popup.add(ErrorPopup, {
                title: _t("Cliente no elegible"),
                body: partner
                    ? _t(
                          "La promoción no aplica para el cliente seleccionado según el dominio de cliente configurado en la regla de lealtad."
                      )
                    : _t("Seleccione un cliente para comprobar la promoción."),
            });
            return false;
        }
        return super._applyReward(reward, coupon_id, potentialQty);
    },
});
