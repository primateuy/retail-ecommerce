# -*- coding: utf-8 -*-


def migrate(cr, version):
    """fenicio_log.mensaje pasa de Text a Json (jsonb). Normaliza el contenido
    existente a JSON válido antes de que Odoo convierta la columna, porque el
    ALTER COLUMN ... USING mensaje::jsonb falla con texto libre no-JSON
    (resúmenes de sincronización manual, strings vacíos, o el repr de Python
    que quedaba guardado antes del fix de action_sync)."""
    cr.execute("""
        UPDATE fenicio_log
        SET mensaje = to_jsonb(mensaje)::text
        WHERE mensaje IS NOT NULL
    """)
