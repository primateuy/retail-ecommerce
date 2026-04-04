# -*- coding: utf-8 -*-
"""Enlaza cada TPV con una configuración de caché opcional."""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = "pos.config"

    bulk_catalog_settings_id = fields.Many2one(
        "pos.bulk.catalog.settings",
        string="Caché catálogo masivo",
        domain="[('company_id', '=', company_id)]",
        help="Si el caché está Listo, se usan productos precargados en lugar del SQL limitado estándar.",
    )

    def _get_limited_product_ids_expanded_for_pos_load(self):
        """Replica la misma selección que get_limited_products_loading (SQL + combos), solo ids.

        El POS no envía todo el catálogo en la carga inicial: aplica límite y orden SQL.
        Filtrar el caché con estos ids evita RPC gigantes y consultas masivas (p. ej. pos_loyalty).
        """
        self.ensure_one()
        Product = self.env["product.product"]
        tables, where_clause, sql_params = Product._where_calc(
            self._get_available_product_domain()
        ).get_sql()
        limit = self.get_limited_product_count()
        query = f"""
            WITH pm AS (
                  SELECT product_id,
                         Max(write_date) date
                    FROM stock_move_line
                GROUP BY product_id
            )
               SELECT product_product.id
                 FROM {tables}
            LEFT JOIN pm ON product_product.id=pm.product_id
                WHERE {where_clause}
                ORDER BY product_product__product_tmpl_id.priority DESC,
                    case when product_product__product_tmpl_id.detailed_type = 'service' then 1 else 0 end DESC,
                    pm.date DESC NULLS LAST,
                    product_product.write_date
                LIMIT %s
        """
        self.env.cr.execute(query, sql_params + [limit])
        product_ids = [row[0] for row in self.env.cr.fetchall()]
        if not product_ids:
            return []
        products = Product.search([("id", "in", product_ids)])
        product_combo = products.filtered(lambda p: p.detailed_type == "combo")
        product_in_combo = product_combo.combo_ids.combo_line_ids.product_id
        seen = set(product_ids)
        extra = [p.id for p in product_in_combo if p.id not in seen]
        return list(product_ids) + extra

    def get_limited_products_loading(self, fields):
        """Sirve desde caché solo el subconjunto que el POS cargaría igual sin caché (límite + orden)."""
        cache = self.bulk_catalog_settings_id
        if cache and cache.state == "ready":
            payload = cache.get_products_for_limited_pos_load(self, fields)
            if payload is not None:
                _logger.info(
                    "pos_bulk_catalog: TPV «%s» — %s productos desde caché "
                    "(mismo criterio/límite que carga POS estándar).",
                    self.name,
                    len(payload),
                )
                return payload
        return super().get_limited_products_loading(fields)
