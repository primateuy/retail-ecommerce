# -*- coding: utf-8 -*-
"""
Migración 17.0.1.1.3: asegura línea outbound OCA con payment_provider_id.

- Si no existe outbound OCA, la crea en el journal con inbound OCA.
- Si existe outbound sin payment_provider_id, la completa.
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
        [('code', '=', 'oca'), ('payment_type', '=', 'inbound')], limit=1,
    )
    outbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'oca'), ('payment_type', '=', 'outbound')], limit=1,
    )
    provider = env['payment.provider'].sudo().search(
        [('code', '=', 'oca')], limit=1,
    )
    if not inbound_method or not outbound_method or not provider:
        _logger.info("OCA migración 17.0.1.1.3: faltan method/provider, skip.")
        return

    for company in env['res.company'].sudo().search([]):
        cr.execute("SAVEPOINT oca_mig_company")
        try:
            inbound_lines = line_model.search([
                ('payment_method_id', '=', inbound_method.id),
                ('journal_id.company_id', '=', company.id),
            ])
            if not inbound_lines:
                cr.execute("RELEASE SAVEPOINT oca_mig_company")
                continue
            journal = inbound_lines[0].journal_id
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
                    "OCA: línea outbound creada en journal %s (compañía %s)",
                    journal.code, company.name,
                )
            elif not existing_outbound.payment_provider_id:
                existing_outbound.write({'payment_provider_id': provider.id})
                _logger.info(
                    "OCA: provider_id completado en outbound (journal %s, compañía %s)",
                    journal.code, company.name,
                )

            for line in inbound_lines:
                if not line.payment_provider_id:
                    line.write({'payment_provider_id': provider.id})

            cr.execute("RELEASE SAVEPOINT oca_mig_company")
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT oca_mig_company")
            _logger.warning(
                "OCA migración 17.0.1.1.3 (compañía %s): %s",
                company.name, exc,
            )
    _logger.info("OCA migración 17.0.1.1.3: terminada")
