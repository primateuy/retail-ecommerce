# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.11: adopta cualquier diario Fiserv pre-existente (sea cual
sea su ``code``) en vez de crear ciegamente uno con ``code='FSVR'``.

Motivo: la 2.0.10 fallaba en agrosiembra con
``"Some payment methods supposed to be unique already exists somewhere else.
(Fiserv ITD)"``. El error viene del constraint
``_check_payment_method_line_ids_multiplicity`` (Odoo 17,
``account/models/account_journal.py``): para métodos de pago electrónicos solo
puede existir UNA ``account.payment.method.line`` por (compañía, payment_method,
payment_provider). En agrosiembra ya había un diario con ``code='FIS'`` (no
'FSVR') con la línea inbound Fiserv configurada manualmente; intentar crear una
segunda línea inbound con el mismo provider en el FSVR nuevo violaba ese
constraint y el savepoint deshacía toda la operación de la compañía.

Estrategia:
  1. Por compañía, primero buscar el diario que **ya tenga** una línea Fiserv
     inbound (con ``payment_provider_id``). Si existe, lo reutilizamos sea cual
     sea su code.
  2. Si su ``code`` no es 'FSVR', lo normalizamos (lo renombramos a 'FSVR') —
     decisión del cliente para uniformar todos los entornos.
  3. Si no encontramos ningún diario Fiserv pre-existente, recién ahí caemos al
     comportamiento anterior: buscar/crear un diario con ``code='FSVR'``.
  4. Sobre el diario resultante creamos la línea outbound si falta y rellenamos
     ``payment_provider_id`` en cualquier línea Fiserv existente que haya
     quedado sin provider (residuo del bug histórico).
  5. Registramos el xml_id ``odoo_pos_fiserv_core.account_journal_fiserv``
     apuntando al diario reutilizado/creado para que ``env.ref()`` siga
     funcionando aunque el diario haya sido pre-existente.

Sigue aplicando el fix de ``account_account.create_asset`` por si la BD vuelve
a entrar a este código sin haber pasado por la 2.0.10 (idempotente).
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
        "Fiserv 17.0.2.0.11: aplicado DEFAULT 'no' a account_account.create_asset"
    )


def _find_existing_fiserv_journal(env, company, provider, inbound_method):
    """
    Devuelve el diario que ya tenga una línea Fiserv inbound integrada (con
    ``payment_provider_id`` apuntando al provider Fiserv) en la compañía,
    sea cual sea su ``code``. Si no encuentra, devuelve un recordset vacío.
    """
    line = env['account.payment.method.line'].sudo().search([
        ('payment_method_id', '=', inbound_method.id),
        ('payment_provider_id', '=', provider.id),
        ('journal_id.company_id', '=', company.id),
    ], limit=1)
    return line.journal_id if line else env['account.journal'].sudo()


def _register_journal_xmlid(env, journal):
    """Registra ``odoo_pos_fiserv_core.account_journal_fiserv`` -> ``journal``."""
    try:
        env['ir.model.data']._update_xmlids([{
            'xml_id': 'odoo_pos_fiserv_core.account_journal_fiserv',
            'record': journal,
            'noupdate': True,
        }])
    except Exception as exc:
        _logger.warning(
            "Fiserv 17.0.2.0.11: no se pudo registrar xml_id account_journal_fiserv: %s",
            exc,
        )


def migrate(cr, version):
    """Adopta diario Fiserv existente (de cualquier code) y completa líneas."""
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    _patch_account_account_create_asset_default(cr)

    env = Environment(cr, SUPERUSER_ID, {})
    provider = env['payment.provider'].sudo().search([('code', '=', 'fiserv')], limit=1)
    if not provider:
        _logger.info(
            "Fiserv 17.0.2.0.11: no hay payment.provider Fiserv; nada que reparar"
        )
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
            "Fiserv 17.0.2.0.11: account.payment.method 'fiserv' inbound no existe; abortando"
        )
        return

    uyu = env.ref('base.UYU', raise_if_not_found=False)

    for company in env['res.company'].sudo().search([]):
        cr.execute("SAVEPOINT fiserv_mig_2_0_11")
        try:
            # 1) Reutilizar diario Fiserv pre-existente (con cualquier code).
            journal = _find_existing_fiserv_journal(
                env, company, provider, inbound_method,
            )

            # 2) Si no hay, fallback al diario con code='FSVR'.
            if not journal:
                journal = journal_model.search(
                    [('code', '=', 'FSVR'), ('company_id', '=', company.id)],
                    limit=1,
                )

            # 3) Sigue sin haber: crear uno nuevo limpio.
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
                    "Fiserv 17.0.2.0.11: diario FSVR creado (compañía %s)",
                    company.name,
                )

            # 4) Normalización pedida por el cliente: code uniforme 'FSVR'.
            if journal.code != 'FSVR':
                old_code = journal.code
                # Defensa: si por algún motivo ya hay otro journal con code FSVR
                # en la misma compañía, no chocar — dejamos el code anterior.
                conflict = journal_model.search([
                    ('code', '=', 'FSVR'),
                    ('company_id', '=', company.id),
                    ('id', '!=', journal.id),
                ], limit=1)
                if conflict:
                    _logger.warning(
                        "Fiserv 17.0.2.0.11: no normalizo code de diario %s -> 'FSVR' "
                        "(compañía %s) porque ya existe otro diario FSVR (id=%s)",
                        old_code, company.name, conflict.id,
                    )
                else:
                    journal.code = 'FSVR'
                    _logger.info(
                        "Fiserv 17.0.2.0.11: diario %s renombrado de '%s' a 'FSVR' (compañía %s)",
                        journal.id, old_code, company.name,
                    )

            # 5) Asegurar líneas inbound/outbound con payment_provider_id.
            for direction, account_pm in (
                ('inbound', inbound_method),
                ('outbound', outbound_method),
            ):
                if not account_pm:
                    _logger.warning(
                        "Fiserv 17.0.2.0.11: account.payment.method 'fiserv' %s no existe; salto",
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
                        "Fiserv 17.0.2.0.11: línea %s creada en diario FSVR (compañía %s)",
                        direction, company.name,
                    )
                elif not line.payment_provider_id:
                    line.payment_provider_id = provider.id
                    _logger.info(
                        "Fiserv 17.0.2.0.11: payment_provider_id seteado en línea %s (id=%s)",
                        direction, line.id,
                    )

            # 6) Asegurar el xml_id para que env.ref() funcione.
            _register_journal_xmlid(env, journal)

            cr.execute("RELEASE SAVEPOINT fiserv_mig_2_0_11")
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT fiserv_mig_2_0_11")
            _logger.warning(
                "Fiserv 17.0.2.0.11 (compañía %s): %s",
                company.name, exc,
            )

    _logger.info("Fiserv 17.0.2.0.11: terminada")
