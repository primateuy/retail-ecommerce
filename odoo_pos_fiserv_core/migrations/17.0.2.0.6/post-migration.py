# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.4: agrega línea outbound Fiserv y hace dedup de journals/líneas.

- Si hay múltiples journals con línea fiserv inbound del mismo provider en la
  misma compañía, conserva el que ya tenía data productiva (TCOC1, etc.) y
  elimina el duplicado creado por hooks previos (FSVR).
- Asegura una línea outbound fiserv en el journal sobreviviente, con el mismo
  payment_provider_id que la inbound.

Envuelto en savepoints para no abortar la transacción global.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    env = Environment(cr, SUPERUSER_ID, {})
    line_model = env['account.payment.method.line'].sudo()
    inbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'inbound')], limit=1,
    )
    outbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'outbound')], limit=1,
    )
    provider = env['payment.provider'].sudo().search(
        [('code', '=', 'fiserv')], limit=1,
    )
    if not inbound_method or not outbound_method or not provider:
        _logger.info("Fiserv migración 17.0.2.0.4: faltan method/provider, skip.")
        return

    for company in env['res.company'].sudo().search([]):
        cr.execute("SAVEPOINT fiserv_mig_company")
        try:
            inbound_lines = line_model.search([
                ('payment_method_id', '=', inbound_method.id),
                ('journal_id.company_id', '=', company.id),
            ])
            if len(inbound_lines) > 1:
                non_fsvr = inbound_lines.filtered(lambda l: l.journal_id.code != 'FSVR')
                keep = non_fsvr[:1] if non_fsvr else inbound_lines[:1]
                duplicates = inbound_lines - keep
                if duplicates:
                    _logger.warning(
                        "Fiserv: deduplicando %s líneas inbound en compañía %s, conservo journal %s",
                        len(duplicates), company.name, keep.journal_id.code,
                    )
                    original_state = provider.state
                    if original_state in ('enabled', 'test'):
                        provider.write({'state': 'disabled'})
                    try:
                        duplicates.unlink()
                    finally:
                        provider.write({'state': original_state})
                inbound_lines = keep

            if not inbound_lines:
                cr.execute("RELEASE SAVEPOINT fiserv_mig_company")
                continue

            journal = inbound_lines.journal_id
            existing_outbound = line_model.search([
                ('payment_method_id', '=', outbound_method.id),
                ('journal_id', '=', journal.id),
            ], limit=1)
            if not existing_outbound:
                line_model.create({
                    'name': outbound_method.name,
                    'payment_method_id': outbound_method.id,
                    'journal_id': journal.id,
                    'payment_provider_id': provider.id,
                })
                _logger.info(
                    "Fiserv: línea outbound creada en journal %s (compañía %s)",
                    journal.code, company.name,
                )
            elif not existing_outbound.payment_provider_id:
                existing_outbound.write({'payment_provider_id': provider.id})

            for line in inbound_lines:
                if not line.payment_provider_id:
                    line.write({'payment_provider_id': provider.id})

            cr.execute("RELEASE SAVEPOINT fiserv_mig_company")
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT fiserv_mig_company")
            _logger.warning(
                "Fiserv migración 17.0.2.0.4 (compañía %s): %s",
                company.name, exc,
            )
    _logger.info("Fiserv migración 17.0.2.0.4: terminada")

    # Corregir payment.transaction con payment_method_id incorrecto.
    try:
        _fix_tx_payment_method(cr)
    except Exception as exc:
        _logger.warning("Fiserv 17.0.2.0.5 fix_tx_payment_method: %s", exc)


def _fix_tx_payment_method(cr):
    """
    Corrige ``payment.transaction`` con provider Fiserv.

    Regla del backend (17.0.2.0.6): si la tx tiene ``account_payment_id``,
    usar el method del pago (via ``payment_method_line_id.payment_provider_id
    .payment_method_ids``). Para tx sin pago contable o de POS, fallback al
    primer method del provider Fiserv global.
    """
    import logging as _lg
    logger = _lg.getLogger(__name__)
    from odoo.api import Environment, SUPERUSER_ID
    env = Environment(cr, SUPERUSER_ID, {})
    provider = env['payment.provider'].sudo().search([('code', '=', 'fiserv')], limit=1)
    if not provider or not provider.payment_method_ids:
        logger.warning("Fiserv 17.0.2.0.6 fix_tx_pm: sin provider o methods.")
        return
    preferred = provider.payment_method_ids.filtered(lambda m: m.code == 'fiserv')
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
        logger.info(
            "Fiserv 17.0.2.0.6: payment.transaction actualizadas. "
            "Desde pago contable=%s, desde provider default=%s (target=%s)",
            n_pay_based, n_default, default_target.code,
        )
