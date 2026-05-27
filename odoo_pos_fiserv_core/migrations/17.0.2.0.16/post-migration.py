# -*- coding: utf-8 -*-
"""
Migración 17.0.2.0.16: paridad fresh-install / update.

Hasta 17.0.2.0.15 el ``post_init_hook`` (instalación fresca) sólo configuraba el
diario Fiserv y sus líneas inbound/outbound para ``env.company``, mientras que
las migraciones 2.0.9 → 2.0.11 (que cubren updates) iteraban todas las
compañías. Consecuencia: instalar el módulo en una BD nueva multi-compañía, o
en una BD con ``account_asset`` enterprise, dejaba la línea outbound Fiserv sin
crear en una o más compañías y el método de pago Fiserv ITD no aparecía en los
pagos salientes.

A partir de 17.0.2.0.16, el ``post_init_hook`` delega en el helper
``setup_fiserv_journals_all_companies`` (compartido con esta migración), por lo
que fresh-install y update producen el mismo estado.

Esta migración invoca el helper para que las BDs que se actualicen a 2.0.16
también recojan eventuales correcciones aún no aplicadas por las migraciones
anteriores (idempotente: si todo está bien, no hace nada).
"""

import logging

from odoo.addons.odoo_pos_fiserv_core.hooks import (
    setup_fiserv_journals_all_companies,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Garantiza diario Fiserv + líneas inbound/outbound en todas las compañías."""
    if not version:
        return
    from odoo.api import Environment, SUPERUSER_ID

    env = Environment(cr, SUPERUSER_ID, {})
    setup_fiserv_journals_all_companies(env)
    _logger.info("Fiserv 17.0.2.0.16: terminada")
