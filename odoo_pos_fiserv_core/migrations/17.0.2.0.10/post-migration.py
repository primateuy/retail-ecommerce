# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.10: idéntica a la 2.0.9 (crea diario FSVR + líneas
inbound/outbound Fiserv en cada compañía) pero con un fix previo para BDs
que tienen ``account_asset`` enterprise instalado.

Problema detectado en agrosiembra:
La 2.0.9 intentó crear el diario tipo ``bank`` y falló al crear las
``account.account`` que Odoo auto-genera (default + suspense) porque la
columna ``create_asset`` de ``account_account`` (módulo enterprise
``account_asset``) está declarada NOT NULL pero el INSERT interno no le
pasa valor. El error es::

    null value in column "create_asset" of relation "account_account"
    violates not-null constraint

Fix: si la columna existe NOT NULL sin default a nivel BD, fijarle un
DEFAULT 'no' con ``ALTER TABLE`` antes de crear el diario. Es totalmente
seguro: no toca registros existentes, solo cubre los INSERTs nuevos donde
el campo no se especifica explícitamente. Idempotente: si ya hay default,
no hace nada.
"""

import logging

_logger = logging.getLogger(__name__)


def _patch_account_account_create_asset_default(cr):
    """Si ``account_account.create_asset`` es NOT NULL sin default, ponele 'no'."""
    cr.execute("""
        SELECT column_default, is_nullable
          FROM information_schema.columns
         WHERE table_name = 'account_account'
           AND column_name = 'create_asset'
    """)
    row = cr.fetchone()
    if not row:
        return
    column_default, is_nullable = row
    if column_default or is_nullable == 'YES':
        return
    cr.execute("""
        ALTER TABLE account_account
        ALTER COLUMN create_asset SET DEFAULT 'no'
    """)
    _logger.info(
        "Fiserv 17.0.2.0.10: aplicado DEFAULT 'no' a account_account.create_asset"
    )


def migrate(cr, version):
    """Asegura diario FSVR + líneas inbound/outbound Fiserv en cada compañía."""
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    _patch_account_account_create_asset_default(cr)

    env = Environment(cr, SUPERUSER_ID, {})
    provider = env['payment.provider'].sudo().search([('code', '=', 'fiserv')], limit=1)
    if not provider:
        _logger.info("Fiserv 17.0.2.0.10: no hay payment.provider Fiserv; nada que reparar")
        return

    line_model = env['account.payment.method.line'].sudo()
    journal_model = env['account.journal'].sudo()
    inbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'inbound')], limit=1,
    )
    outbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'outbound')], limit=1,
    )
    if not inbound_method:
        _logger.warning(
            "Fiserv 17.0.2.0.10: account.payment.method 'fiserv' inbound no existe; abortando"
        )
        return

    uyu = env.ref('base.UYU', raise_if_not_found=False)

    for company in env['res.company'].sudo().search([]):
        cr.execute("SAVEPOINT fiserv_mig_2_0_10")
        try:
            journal = journal_model.search(
                [('code', '=', 'FSVR'), ('company_id', '=', company.id)],
                limit=1,
            )
            if not journal:
                journal_vals = {
                    'name': 'Fiserv ITD',
                    'code': 'FSVR',
                    'type': 'bank',
                    'company_id': company.id,
                }
                if uyu:
                    journal_vals['currency_id'] = uyu.id
                journal = journal_model.create(journal_vals)
                _logger.info(
                    "Fiserv 17.0.2.0.10: diario FSVR creado (compañía %s)",
                    company.name,
                )

            for direction, account_pm in (
                ('inbound', inbound_method),
                ('outbound', outbound_method),
            ):
                if not account_pm:
                    _logger.warning(
                        "Fiserv 17.0.2.0.10: account.payment.method 'fiserv' %s no existe; salto",
                        direction,
                    )
                    continue
                line = line_model.search([
                    ('journal_id', '=', journal.id),
                    ('payment_method_id', '=', account_pm.id),
                ], limit=1)
                if not line:
                    line_model.create({
                        'name': account_pm.name,
                        'payment_method_id': account_pm.id,
                        'journal_id': journal.id,
                        'payment_provider_id': provider.id,
                    })
                    _logger.info(
                        "Fiserv 17.0.2.0.10: línea %s creada en diario FSVR (compañía %s)",
                        direction, company.name,
                    )
                elif not line.payment_provider_id:
                    line.payment_provider_id = provider.id
                    _logger.info(
                        "Fiserv 17.0.2.0.10: payment_provider_id seteado en línea %s (id=%s)",
                        direction, line.id,
                    )
            cr.execute("RELEASE SAVEPOINT fiserv_mig_2_0_10")
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT fiserv_mig_2_0_10")
            _logger.warning(
                "Fiserv 17.0.2.0.10 (compañía %s): %s",
                company.name, exc,
            )

    _logger.info("Fiserv 17.0.2.0.10: terminada")
