# -*- coding: utf-8 -*-
"""Intercepta socios e ítems de tarifa para servir desde el caché bulk.

Los productos pasan por ``pos.config.get_limited_products_loading`` (caché limitado al mismo
subconjunto que el POS estándar); no se sobrescribe ``_get_pos_ui_product_product`` para
no duplicar lógica ni romper la cadena con pos_loyalty.
"""
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _get_pos_ui_res_partner(self, params):
        """Misma ventana que Odoo: solo los ~100 partners del SQL limitado, datos desde caché.

        Devolver todos los partners del caché rompe pos_loyalty (_read_group con IN enorme)
        y bloquea la carga del POS.
        """
        cache = self.config_id.bulk_catalog_settings_id
        if cache and cache.state == "ready":
            if not cache.chunk_ids.filtered(lambda c: c.kind == "partner"):
                return super()._get_pos_ui_res_partner(params)
            partner_ids = [res[0] for res in self.config_id.get_limited_partners_loading()]
            partner_id_set = set(partner_ids)
            target = len(partner_id_set)
            names = cache._field_names_ensure_id(params["search_params"]["fields"])
            # Streaming por fragmentos; parar al tener los ~100 socios (sin recorrer todo el caché).
            by_id = {}
            for row in cache._iter_rows_from_chunks("partner"):
                pid = row.get("id")
                if pid in partner_id_set:
                    by_id[pid] = {fn: row.get(fn) for fn in names}
                if len(by_id) == target:
                    break
            ordered = []
            missing_ids = []
            for pid in partner_ids:
                if pid in by_id:
                    ordered.append(by_id[pid])
                else:
                    missing_ids.append(pid)
            if missing_ids:
                extra = self.env["res.partner"].search_read(
                    [("id", "in", missing_ids)],
                    fields=params["search_params"]["fields"],
                )
                extra_by_id = {e["id"]: e for e in extra}
                ordered = []
                for pid in partner_ids:
                    if pid in by_id:
                        ordered.append(by_id[pid])
                    elif pid in extra_by_id:
                        ordered.append(extra_by_id[pid])
            return ordered
        return super()._get_pos_ui_res_partner(params)

    def _prepare_product_pricelists(self, pricelists):
        """Adjunta ítems de tarifa desde el caché si existe."""
        cache = self.config_id.bulk_catalog_settings_id
        if cache and cache.state == "ready":
            items = cache.get_pricelist_items_raw()
            if items is not None:
                by_id = {p["id"]: p for p in pricelists}
                for pl in pricelists:
                    pl["items"] = []
                for item in items:
                    pl_tuple = item.get("pricelist_id")
                    if not pl_tuple:
                        continue
                    pid = pl_tuple[0]
                    if pid in by_id:
                        by_id[pid]["items"].append(item)
                return pricelists
        return super()._prepare_product_pricelists(pricelists)
