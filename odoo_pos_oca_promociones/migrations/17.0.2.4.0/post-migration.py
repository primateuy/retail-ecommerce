# -*- coding: utf-8 -*-
"""
Migración: cada cobro con promoción cuenta para la promoción de su proveedor OCA.

Hasta la 17.0.2.3.0 la promoción se buscaba con la compañía del proceso, que en el hilo del
pinpad es siempre la principal: las cajas de todas las compañías aplicaban la de Surf. Desde
ahora se elige por el proveedor OCA de la caja; acá se reasignan los cobros ya registrados a la
promoción de su proveedor (``payment_transaction.provider_id``), sólo cuando ese proveedor
tiene exactamente una promoción. No toca montos, órdenes ni asientos.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE payment_transaction t
           SET oca_promotion_id = p.id
          FROM (SELECT payment_provider_id, MIN(id) AS id
                  FROM payment_method_promotion
                 GROUP BY payment_provider_id
                HAVING COUNT(*) = 1) p
         WHERE t.oca_promotion_id IS NOT NULL
           AND t.provider_id = p.payment_provider_id
           AND t.oca_promotion_id <> p.id
    """)
    _logger.info("Promociones OCA: %s cobro(s) reasignados a la promoción de su proveedor.",
                 cr.rowcount)
