# -*- coding: utf-8 -*-
"""
Migración 17.0.2.1.1: corrige ``payment.transaction`` con provider OCA.

Regla del backend: si la tx tiene ``account_payment_id``, usar el method del
pago (via ``payment_method_line_id.payment_provider_id.payment_method_ids``).
Para tx sin pago contable o de POS, fallback al primer method del provider
OCA global.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    provider = env['payment.provider'].sudo().search([('code', '=', 'oca')], limit=1)
    if not provider or not provider.payment_method_ids:
        _logger.info("OCA 17.0.2.1.1: sin provider o methods, skip.")
        return
    preferred = provider.payment_method_ids.filtered(lambda m: m.code == 'oca')
    default_target = (preferred[:1] or provider.payment_method_ids[:1])
    if not default_target:
        return
    txs = env['payment.transaction'].sudo().search([('provider_id', '=', provider.id)])
    n_pay_based = 0
    n_default = 0
    for tx in txs:
        target = False
        if tx.account_payment_id:
            pay_line = tx.account_payment_id.payment_method_line_id
            prov_line = pay_line.payment_provider_id if pay_line else False
            if prov_line and prov_line.payment_method_ids:
                pref = prov_line.payment_method_ids.filtered(
                    lambda m: m.code == prov_line.code
                )
                target = (pref[:1] or prov_line.payment_method_ids[:1])
        if not target:
            target = default_target
        if tx.payment_method_id != target:
            tx.payment_method_id = target.id
            if tx.account_payment_id:
                n_pay_based += 1
            else:
                n_default += 1
    if n_pay_based or n_default:
        _logger.info(
            "OCA 17.0.2.1.1: payment.transaction actualizadas. "
            "Desde pago contable=%s, desde provider default=%s (target=%s)",
            n_pay_based, n_default, default_target.code,
        )
