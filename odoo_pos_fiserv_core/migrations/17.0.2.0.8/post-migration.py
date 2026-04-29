# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.8: garantiza líneas de método de pago Fiserv (inbound + outbound)
en el diario FSVR de cada compañía, con ``payment_provider_id`` correctamente seteado.

Motivo: el ``post_init_hook`` solo corre al instalar el módulo y, además, hasta
2.0.7 la función ``_ensure_journal_payment_method_line`` se llamaba con un
argumento extra (``provider``) que su firma no aceptaba — TypeError silenciado
por el ``try/except`` de ``_ensure_fiserv_journal``. Resultado: en bases ya
instaladas la línea outbound (y a veces también la inbound) nunca se creó, y
desde el form de ``account.payment`` outbound no aparece el método Fiserv ITD.

La migración 2.0.6 anterior asumía que **ya** existía línea inbound y se
saltaba si no la había. Esta migración no asume nada y cubre todos los casos:
crea ambas líneas si faltan y rellena ``payment_provider_id`` si quedó vacío.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Asegura líneas inbound/outbound Fiserv en el journal FSVR de cada compañía."""
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    env = Environment(cr, SUPERUSER_ID, {})
    provider = env['payment.provider'].sudo().search([('code', '=', 'fiserv')], limit=1)
    if not provider:
        _logger.info("Fiserv 17.0.2.0.8: no hay payment.provider Fiserv; nada que reparar")
        return

    line_model = env['account.payment.method.line'].sudo()
    inbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'inbound')], limit=1,
    )
    outbound_method = env['account.payment.method'].sudo().search(
        [('code', '=', 'fiserv'), ('payment_type', '=', 'outbound')], limit=1,
    )
    if not inbound_method:
        _logger.warning(
            "Fiserv 17.0.2.0.8: account.payment.method 'fiserv' inbound no existe; abortando"
        )
        return

    for company in env['res.company'].sudo().search([]):
        cr.execute("SAVEPOINT fiserv_mig_2_0_8")
        try:
            journal = env['account.journal'].sudo().search(
                [('code', '=', 'FSVR'), ('company_id', '=', company.id)],
                limit=1,
            )
            # Si esta compañía no tiene aún el journal FSVR, la migración no
            # debe crearlo: solo el ``post_init_hook`` lo hace al instalar.
            # Una compañía sin journal Fiserv simplemente no usa la integración.
            if not journal:
                cr.execute("RELEASE SAVEPOINT fiserv_mig_2_0_8")
                continue

            for direction, account_pm in (
                ('inbound', inbound_method),
                ('outbound', outbound_method),
            ):
                if not account_pm:
                    _logger.warning(
                        "Fiserv 17.0.2.0.8: account.payment.method 'fiserv' %s no existe; salto",
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
                        "Fiserv 17.0.2.0.8: línea %s creada en journal FSVR (compañía %s)",
                        direction, company.name,
                    )
                elif not line.payment_provider_id:
                    line.payment_provider_id = provider.id
                    _logger.info(
                        "Fiserv 17.0.2.0.8: payment_provider_id seteado en línea %s (id=%s)",
                        direction, line.id,
                    )
            cr.execute("RELEASE SAVEPOINT fiserv_mig_2_0_8")
        except Exception as exc:
            cr.execute("ROLLBACK TO SAVEPOINT fiserv_mig_2_0_8")
            _logger.warning(
                "Fiserv 17.0.2.0.8 (compañía %s): %s",
                company.name, exc,
            )

    _logger.info("Fiserv 17.0.2.0.8: terminada")
