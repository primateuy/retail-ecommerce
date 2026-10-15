# -*- coding: utf-8 -*-
"""
Migración: la promoción de cada cobro pasa a guardarse en la transacción.

El contador «Veces Aplicada» ya no se suma durante el cobro (chocaba entre cajas y el choque
deshacía el pago); se cuenta desde ``payment.transaction.oca_promotion_id``. Acá se completa ese
campo en las transacciones existentes con el ``promotion_id`` que ya guardaban en el JSON de
``oca_complete_response``. Se lee en Python porque el texto puede no ser JSON válido.
"""

import json
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT id FROM payment_method_promotion")
    promociones = {fila[0] for fila in cr.fetchall()}
    cr.execute("""
        SELECT id, oca_complete_response
          FROM payment_transaction
         WHERE is_promotion
           AND oca_promotion_id IS NULL
           AND oca_complete_response LIKE '%%promotion_id%%'
    """)
    por_promocion = {}
    sin_promocion = 0
    for transaccion_id, respuesta in cr.fetchall():
        try:
            promotion_id = (json.loads(respuesta).get('promotion_info') or {}).get('promotion_id')
        except (ValueError, AttributeError):
            promotion_id = None
        if promotion_id in promociones:
            por_promocion.setdefault(promotion_id, []).append(transaccion_id)
        else:
            sin_promocion += 1
    for promotion_id, ids in por_promocion.items():
        cr.execute(
            "UPDATE payment_transaction SET oca_promotion_id = %s WHERE id IN %s",
            (promotion_id, tuple(ids)),
        )
    _logger.info(
        "Promociones OCA: %s transacción(es) vinculadas a su promoción; %s sin promoción reconocible.",
        sum(len(ids) for ids in por_promocion.values()), sin_promocion,
    )
