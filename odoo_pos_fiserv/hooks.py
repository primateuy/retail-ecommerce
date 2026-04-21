# -*- coding: utf-8 -*-
"""
Hooks de instalación del módulo POS Fiserv ITD.

Tras la carga de datos XML, asegura proveedor, diario, método POS y vinculación
del método de pago Card al proveedor Fiserv.
"""

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Punto de entrada del post_init_hook declarado en __manifest__.py.

    Se usa para completar datos que el XML deja incompletos (p. ej. métodos de pago
    en el diario) o para crear registros si faltan, sin bloquear la instalación.

    Args:
        env (api.Environment): Entorno con la compañía del usuario sistema.
    """
    try:
        # Bloque: orquestación de tareas de post-instalación.
        _logger.info("Post-instalación odoo_pos_fiserv: inicio")
        _ensure_fiserv_provider(env)
        _ensure_fiserv_journal(env)
        _ensure_fiserv_pos_payment_method(env)
        _link_card_payment_method_to_fiserv(env)
        _link_pos_method_to_fiserv_provider(env)
        _logger.info("Post-instalación odoo_pos_fiserv: completada")
    except Exception as exc:
        # Bloque: registro del error sin relanzar (no debe abortar -u del módulo).
        _logger.error("Post-instalación odoo_pos_fiserv: error %s", exc, exc_info=True)


def _ensure_fiserv_provider(env):
    """
    Garantiza un registro payment.provider con code=fiserv.

    El XML de datos ya crea el proveedor; esta función cubre instalaciones parciales
    o bases donde se borró el registro manualmente.
    """
    try:
        # Bloque: salida temprana si el proveedor ya existe.
        provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
        if provider:
            return
        payment_method = env["payment.method"].search([("code", "=", "fiserv")], limit=1)
        if not payment_method:
            _logger.warning("No existe payment.method fiserv; omito crear proveedor")
            return
        # Bloque: alta mínima del proveedor enlazado al método fiserv.
        env["payment.provider"].create(
            {
                "name": "Fiserv ITD",
                "code": "fiserv",
                "state": "test",
                "allow_tokenization": True,
                "payment_method_ids": [(6, 0, [payment_method.id])],
                "company_id": env.company.id,
            }
        )
        _logger.info("Proveedor Fiserv creado en post_init")
    except Exception as exc:
        _logger.error("_ensure_fiserv_provider: %s", exc, exc_info=True)


def _ensure_fiserv_journal(env):
    """
    Crea o completa el diario bancario FSVR con métodos inbound/outbound fiserv.

    El XML crea el diario sin líneas de método; aquí se enlaza account.payment.method.
    """
    try:
        # Bloque: localizar diario y método de pago contable fiserv.
        journal = env["account.journal"].search(
            [("code", "=", "FSVR"), ("company_id", "=", env.company.id)],
            limit=1,
        )
        account_pm = env["account.payment.method"].search(
            [("code", "=", "fiserv"), ("payment_type", "=", "inbound")],
            limit=1,
        )
        if not account_pm:
            _logger.warning("No existe account.payment.method fiserv inbound")
            return
        if not journal:
            # Bloque: creación del diario con moneda UYU por defecto.
            journal = env["account.journal"].create(
                {
                    "name": "Fiserv ITD",
                    "code": "FSVR",
                    "type": "bank",
                    "company_id": env.company.id,
                    "currency_id": env.ref("base.UYU").id,
                    "inbound_payment_method_ids": [(6, 0, [account_pm.id])],
                    "outbound_payment_method_ids": [(6, 0, [account_pm.id])],
                }
            )
            _logger.info("Diario Fiserv FSVR creado")
            return
        # Bloque: diario ya existente (cargado por XML) — completar M2M si faltan.
        if account_pm not in journal.inbound_payment_method_ids:
            journal.inbound_payment_method_ids = [(4, account_pm.id)]
        if account_pm not in journal.outbound_payment_method_ids:
            journal.outbound_payment_method_ids = [(4, account_pm.id)]
    except Exception as exc:
        _logger.error("_ensure_fiserv_journal: %s", exc, exc_info=True)


def _ensure_fiserv_pos_payment_method(env):
    """
    Crea pos.payment.method con use_payment_terminal=fiserv si no hay ninguno.

    Asigna receivable_account_id porque en muchas compañías el POS lo exige para
    métodos no efectivo; el XML demo puede omitirlo y delegar aquí.
    """
    try:
        # Bloque: no duplicar si ya existe un método terminal Fiserv.
        pos_pm = env["pos.payment.method"].search(
            [("use_payment_terminal", "=", "fiserv")],
            limit=1,
        )
        if pos_pm:
            return
        receivable = env["account.account"].search(
            [
                ("account_type", "=", "asset_receivable"),
                ("company_id", "=", env.company.id),
            ],
            limit=1,
        )
        if not receivable:
            _logger.error("No hay cuenta por cobrar; no se crea método POS Fiserv")
            return
        # Bloque: valores por defecto y enlace opcional al proveedor Fiserv.
        provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
        vals = {
            "name": "Fiserv ITD",
            "use_payment_terminal": "fiserv",
            "receivable_account_id": receivable.id,
            "is_cash_count": False,
            "active": True,
            "sequence": 11,
            "url_webservice": "https://testitd.firstdata.com/v2/ITDService",
            "codigo_sistema": "1",
            "codigo_terminal": "001",
            "client_app_id": "1",
            "codigo_sucursal": 1,
        }
        if provider:
            vals["fiserv_provider_id"] = provider.id
        env["pos.payment.method"].create(vals)
        _logger.info("Método POS Fiserv creado en post_init")
    except Exception as exc:
        _logger.error("_ensure_fiserv_pos_payment_method: %s", exc, exc_info=True)


def _link_card_payment_method_to_fiserv(env):
    """
    Añade el método core `card` al proveedor Fiserv si aún no está asociado.

    Sin esto, algunos flujos de payment esperan card asociado al proveedor.
    """
    try:
        # Bloque: buscar proveedor y método card del core.
        fiserv_provider = env["payment.provider"].search(
            [("code", "=", "fiserv")],
            limit=1,
        )
        if not fiserv_provider:
            return
        card_pm = env["payment.method"].search([("code", "=", "card")], limit=1)
        if not card_pm or card_pm in fiserv_provider.payment_method_ids:
            return
        fiserv_provider.payment_method_ids = [(4, card_pm.id)]
        _logger.info("Método Card vinculado al proveedor Fiserv")
    except Exception as exc:
        _logger.error("_link_card_payment_method_to_fiserv: %s", exc, exc_info=True)


def _link_pos_method_to_fiserv_provider(env):
    """
    Completa fiserv_provider_id en métodos POS ya creados sin proveedor.

    Evita que queden URL/SystemId desincronizados respecto al payment.provider.
    """
    try:
        # Bloque: actualización masiva solo donde falta el enlace.
        provider = env["payment.provider"].search([("code", "=", "fiserv")], limit=1)
        if not provider:
            return
        methods = env["pos.payment.method"].search(
            [
                ("use_payment_terminal", "=", "fiserv"),
                ("fiserv_provider_id", "=", False),
            ]
        )
        if methods:
            methods.write({"fiserv_provider_id": provider.id})
    except Exception as exc:
        _logger.error("_link_pos_method_to_fiserv_provider: %s", exc, exc_info=True)
