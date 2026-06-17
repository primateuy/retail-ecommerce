# -*- coding: utf-8 -*-
"""Limpieza de marcas manuales superadas por el catálogo del Anexo 4.

Antes de este release, las marcas por código de issuer bajo `payment_method_oca` se cargaban
a mano (sin xmlid) y con duplicados ambiguos (p. ej. dos registros con code='21': Mastercard y
OCA). El nuevo `data/oca_card_brands.xml` define el catálogo oficial (con xmlid) por código.

Esta migración elimina las marcas hijas de `payment_method_oca` que tengan código numérico,
NO estén gestionadas por xmlid (las manuales) y NO estén referenciadas por ninguna transacción,
para que el lookup por código quede sin ambigüedad.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM payment_method pm
        USING ir_model_data dp
        WHERE dp.model = 'payment.method'
          AND dp.module = 'odoo_pos_oca_core'
          AND dp.name = 'payment_method_oca'
          AND dp.res_id = pm.primary_payment_method_id
          AND pm.code ~ '^[0-9]+$'
          AND NOT EXISTS (
              SELECT 1 FROM ir_model_data d
              WHERE d.model = 'payment.method' AND d.res_id = pm.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM payment_transaction t WHERE t.payment_method_id = pm.id
          )
        RETURNING pm.id, pm.code
        """
    )
    borradas = cr.fetchall()
    if borradas:
        _logger.info(
            "odoo_pos_oca_core 2.3.0: eliminadas %s marcas manuales (sin xmlid) bajo "
            "payment_method_oca, superadas por el Anexo 4: %s",
            len(borradas), borradas,
        )
