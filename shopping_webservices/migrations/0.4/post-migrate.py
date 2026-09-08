"""Migración 0.4: elimina shopping_code de shopping.payment.method.

Dos tareas que Odoo no hace por su cuenta al borrar un campo del código:
la columna huérfana queda en la tabla, y el campo name (computado con
store=True) conserva el valor viejo porque el recálculo se dispara por
cambios en las dependencias, no por cambios en la lógica del compute.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # El constraint pasó a ser unique(payment_code): si hay códigos repetidos
    # entre shoppings, Odoo no puede crearlo y solo deja un warning.
    cr.execute("""
        SELECT payment_code, count(*)
        FROM shopping_payment_method
        GROUP BY payment_code
        HAVING count(*) > 1
    """)
    duplicates = cr.fetchall()
    if duplicates:
        _logger.warning(
            "shopping.payment.method: códigos de pago duplicados, el constraint "
            "unique(payment_code) no podrá crearse: %s",
            ", ".join("%s (%s registros)" % (code, count) for code, count in duplicates),
        )

    # Al borrar la columna PostgreSQL descarta también el viejo
    # unique(shopping_code, payment_code) que dependía de ella.
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id = (
            SELECT id FROM ir_model_fields
            WHERE model = 'shopping.payment.method'
              AND name = 'shopping_code'
        )
    """)
    cr.execute("ALTER TABLE shopping_payment_method DROP COLUMN IF EXISTS shopping_code")

    env = api.Environment(cr, SUPERUSER_ID, {})
    records = env['shopping.payment.method'].search([])
    if records:
        env.add_to_compute(records._fields['name'], records)
        records.flush_recordset(['name'])
        _logger.info("shopping.payment.method: name recalculado en %s registros", len(records))
