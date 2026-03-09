/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Order } from "@point_of_sale/app/store/models";
import { RewardButton } from "@pos_loyalty/app/control_buttons/reward_button";

function getMany2OneId(value) {
    if (Array.isArray(value)) {
        return value[0];
    }
    return value || false;
}

function getMany2ManyIds(value) {
    return Array.isArray(value) ? value : [];
}

function getRecordField(record, fieldName) {
    const value = record?.[fieldName];
    if (fieldName.endsWith('_id')) {
        if (Array.isArray(value) && value.length === 2) {
            return value[0];
        }
    }
    return value;
}

function compareValues(left, operator, right) {
    const leftMany2one = getMany2OneId(left);
    const rightMany2one = getMany2OneId(right);
    const leftMany2many = getMany2ManyIds(left);
    const rightMany2many = getMany2ManyIds(right);

    switch (operator) {
        case '=':
            if (Array.isArray(left)) {
                return leftMany2one === rightMany2one;
            }
            return left === right;
        case '!=':
            if (Array.isArray(left)) {
                return leftMany2one !== rightMany2one;
            }
            return left !== right;
        case 'in':
            if (Array.isArray(left)) {
                if (leftMany2many.length) {
                    return leftMany2many.some((id) => rightMany2many.includes(id) || right.includes?.(id));
                }
                return (rightMany2many.length ? rightMany2many : right).includes(leftMany2one);
            }
            return (Array.isArray(right) ? right : rightMany2many).includes(left);
        case 'not in':
            return !compareValues(left, 'in', right);
        case '>':
            return left > right;
        case '>=':
            return left >= right;
        case '<':
            return left < right;
        case '<=':
            return left <= right;
        case 'ilike': {
            const leftText = String(left || '').toLowerCase();
            const rightText = String(right || '').toLowerCase();
            return leftText.includes(rightText);
        }
        case 'like':
            return String(left || '').includes(String(right || ''));
        case '=?':
            return !right || compareValues(left, '=', right);
        default:
            return true;
    }
}

function evalDomainNode(record, node) {
    if (!Array.isArray(node)) {
        return true;
    }

    // Leaf condition: ['field', '=', value]
    if (typeof node[0] === 'string' && !['&', '|', '!'].includes(node[0]) && node.length === 3) {
        const [fieldName, operator, value] = node;
        return compareValues(getRecordField(record, fieldName), operator, value);
    }

    // Prefix notation nodes.
    const token = node[0];
    if (token === '!') {
        return !evalDomainNode(record, node[1]);
    }
    if (token === '&') {
        return evalDomainNode(record, node[1]) && evalDomainNode(record, node[2]);
    }
    if (token === '|') {
        return evalDomainNode(record, node[1]) || evalDomainNode(record, node[2]);
    }

    // Flat list of leaves => AND.
    return node.every((item) => evalDomainNode(record, item));
}

function getProgramsCollection(pos) {
    const collection = (
        pos.programs ||
        pos.program_by_id ||
        pos['loyalty.program'] ||
        pos.data?.['loyalty.program'] ||
        []
    );
    if (!collection || (Array.isArray(collection) && !collection.length && !Object.keys(collection).length)) {
        console.warn('[loyalty_customer_domain_pos] No se encontró la colección loyalty.program en el store del POS. Los filtros de cliente no se aplicarán.');
    }
    return collection;
}

function getRulesCollection(pos) {
    const collection = (
        pos.rules ||
        pos.rule_by_id ||
        pos['loyalty.rule'] ||
        pos.data?.['loyalty.rule'] ||
        []
    );
    if (!collection || (Array.isArray(collection) && !collection.length && !Object.keys(collection).length)) {
        console.warn('[loyalty_customer_domain_pos] No se encontró la colección loyalty.rule en el store del POS. Los filtros de cliente no se aplicarán.');
    }
    return collection;
}

function getById(collection, id) {
    if (!collection || !id) {
        return null;
    }
    if (collection[id]) {
        return collection[id];
    }
    if (Array.isArray(collection)) {
        return collection.find((item) => item.id === id) || null;
    }
    const values = Object.values(collection);
    return values.find((item) => item.id === id) || null;
}

function getProgram(pos, programId) {
    return getById(getProgramsCollection(pos), programId);
}

function getRule(pos, ruleRef) {
    if (!ruleRef) {
        return null;
    }
    if (typeof ruleRef === 'object' && ruleRef.id) {
        return ruleRef;
    }
    return getById(getRulesCollection(pos), Array.isArray(ruleRef) ? ruleRef[0] : ruleRef);
}

function getRulesForProgram(pos, program) {
    if (!program) {
        return [];
    }
    const refs = program.rule_ids || [];
    return refs.map((ruleRef) => getRule(pos, ruleRef)).filter(Boolean);
}

function getProgramIdFromReward(reward) {
    if (!reward) {
        return false;
    }
    if (reward.program_id) {
        return Array.isArray(reward.program_id) ? reward.program_id[0] : reward.program_id;
    }
    if (reward.program?.id) {
        return reward.program.id;
    }
    if (reward.reward?.program_id) {
        return Array.isArray(reward.reward.program_id)
            ? reward.reward.program_id[0]
            : reward.reward.program_id;
    }
    return false;
}

function partnerMatchesProgram(pos, partner, programId) {
    if (!programId) {
        return true;
    }
    const program = getProgram(pos, programId);
    if (!program) {
        return true;
    }
    const rules = getRulesForProgram(pos, program);
    const customerRules = rules.filter((rule) => rule.customer_domain && rule.customer_domain !== '[]');
    if (!customerRules.length) {
        return true;
    }
    if (!partner) {
        return false;
    }
    return customerRules.some((rule) => {
        try {
            const domain = JSON.parse(rule.customer_domain);
            return evalDomainNode(partner, domain);
        } catch {
            // Si el domain está mal formado, se permite la recompensa para no bloquear al cajero
            return true;
        }
    });
}

function filterRewardsForPartner(order, rewards) {
    const partner = order.get_partner();
    const pos = order.pos;
    if (!Array.isArray(rewards)) {
        return rewards;
    }
    return rewards.filter((reward) => partnerMatchesProgram(pos, partner, getProgramIdFromReward(reward)));
}

patch(Order.prototype, {
    getClaimableRewards() {
        const rewards = super.getClaimableRewards(...arguments);
        return filterRewardsForPartner(this, rewards);
    },

    getPotentialFreeProductRewards() {
        const rewards = super.getPotentialFreeProductRewards?.(...arguments);
        return filterRewardsForPartner(this, rewards);
    },
});

patch(RewardButton.prototype, {
    async _applyReward(reward, couponId, potentialQty) {
        const order = this.pos.get_order();
        const partner = order?.get_partner();
        if (!partnerMatchesProgram(this.pos, partner, getProgramIdFromReward(reward))) {
            this.dialog.add(AlertDialog, {
                title: "Cliente no elegible",
                body: partner
                    ? "La promoción no aplica para el cliente seleccionado según el dominio de cliente de la regla."
                    : "Seleccione un cliente elegible para poder aplicar esta promoción.",
            });
            return;
        }
        return super._applyReward(reward, couponId, potentialQty);
    },
});
