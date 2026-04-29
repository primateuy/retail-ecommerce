# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.9: garantiza el diario FSVR + líneas Fiserv (inbound/outbound)
en cada compañía, con ``payment_provider_id`` correctamente seteado.

Motivo: la migración 2.0.8 reparaba las líneas pero saltaba la compañía si no
existía el diario FSVR — bajo el supuesto de que "una compañía sin diario no
usa la integración". Ese supuesto falla en BDs legacy donde el módulo se
instaló en una versión vieja del ``post_init_hook`` que no creaba el diario
(comentario en ``hooks.py``: «antes se omitía esta creación por temor a
colisiones con módulos Enterprise»). Resultado: con ``odoo_pos_fiserv_backend``
instalado pero sin diario FSVR, no aparece el método saliente Fiserv en el form
de ``account.payment``.

Como los hooks no corren con ``-u``, esta migración cubre lo que el hook
debería haber hecho: crea el diario si falta y luego las dos líneas.
Idempotente: si el diario y las líneas ya están bien, no hace nada.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Asegura diario FSVR + líneas inbound/outbound Fiserv en cada compañía."""
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    env = Environment(cr, SUPERUSER_ID, {})
    provider = env['payment.provider'].sudo().search([('code', '=', 'fiserv')], limit=1)
    if not provider:
        _logger.info("Fiserv 17.0.2.0.9: no hay payment.provider Fiserv; nada que reparar")
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
            "Fiserv 17.0.2.0.9: account.payment.method 'fiserv' inbound no existe; abortando"
        )
        return

    uyu = env.ref('base.UYU', raise_if_not_found=False)

    for company in env['res.company'].sudo().search([]):
        cr.execute("SAVEPOINT fiserv_mig_2_0_9")
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
                    "Fiserv 17.0.2.0.9: diario FSVR creado (compañía %s)",
                    company.name,
                )

            for direction, account_pm in (
                ('inbound', inbound_method),
                ('outbound', outbound_method),
            ):
                if not account_pm:
                    _logger.warning(
                        "Fiserv 17.0.2.0.9: account.payment.method 'fiserv' %s no existe; salto",
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
                        "Fiserv 17.0.2.0.9: línea %s creada en diario FSVR (compañía %s)",
                        direction, company.name,
                    )
                elif not line.payment_provider_id:
                    line.payment_provider_id = provider.id
                    _logger.info(
                        "Fiserv 17.0.2.0.9: payment_provider_id seteado en línea %s (id=%s)",
                        direction, line.id,
                    )
            cr.execute("RELEASE SAVEPOINT fiserv_mig_2_0_9")
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT fiserv_mig_2_0_9")
            _logger.warning(
                "Fiserv 17.0.2.0.9 (compañía %s): %s",
                company.name, exc,
            )

    _logger.info("Fiserv 17.0.2.0.9: terminada")
