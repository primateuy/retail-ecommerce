# -*- coding: utf-8 -*-
"""Fragmentos comprimidos del catálogo (productos, partners o ítems de tarifa)."""
import base64
import gzip
import json
from odoo import fields, models


class PosBulkCatalogChunk(models.Model):
    """Almacena un lote del caché en gzip+JSON para no saturar memoria en una sola fila."""

    _name = "pos.bulk.catalog.chunk"
    _description = "POS Bulk Catalog Chunk"
    _order = "settings_id, kind, sequence"

    settings_id = fields.Many2one(
        "pos.bulk.catalog.settings",
        string="Configuración",
        required=True,
        ondelete="cascade",
        index=True,
    )
    kind = fields.Selection(
        [
            ("product", "Productos"),
            ("partner", "Clientes"),
            ("pricelist_item", "Ítems de lista de precios"),
        ],
        required=True,
        index=True,
    )
    sequence = fields.Integer(default=1, required=True)
    payload = fields.Binary(string="Datos (gzip)", attachment=True, required=True)

    def decode_rows(self):
        """Descomprime el payload y devuelve la lista de diccionarios."""
        self.ensure_one()
        if not self.payload:
            return []
        raw = base64.b64decode(self.payload)
        data = json.loads(gzip.decompress(raw).decode("utf-8"))
        return data if isinstance(data, list) else []
