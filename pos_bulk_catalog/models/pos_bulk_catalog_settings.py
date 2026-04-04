# -*- coding: utf-8 -*-
"""
Configuración y construcción del caché masivo para el POS.

Objetivo: mismo propósito que módulos tipo pos_fast_loading pero:
- Sin sobrescribir product.product.search_read a nivel global.
- Construcción en segundo plano vía cron (no bloquea el clic en el navegador).
- Paginación estable por id (keyset) y lotes configurables.
- Opción de excluir image_128 para entornos con filestore incompleto.
"""
import base64
import gzip
import json
import logging
import time
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools import date_utils

_logger = logging.getLogger(__name__)

# Lock único para que no corran dos crons/workers construyendo a la vez (evita pico doble de carga).
_PG_ADVISORY_LOCK_POS_BULK = 872_364_123


class PosBulkCatalogSettings(models.Model):
    """Parámetros del caché y orquestación de la construcción por fases."""

    _name = "pos.bulk.catalog.settings"
    _description = "POS Bulk Catalog Settings"

    name = fields.Char(required=True, default="Catálogo POS")
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)
    reference_pos_config_id = fields.Many2one(
        "pos.config",
        string="Punto de venta de referencia",
        required=True,
        domain="[('company_id', '=', company_id)]",
        help="Se usa su dominio de productos disponibles y compañía para armar el caché.",
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("building", "Construyendo"),
            ("ready", "Listo"),
            ("error", "Error"),
        ],
        default="draft",
        readonly=True,
        copy=False,
    )
    build_stage = fields.Selection(
        [
            ("product", "Productos"),
            ("partner", "Clientes"),
            ("pricelist", "Tarifas"),
            ("done", "Finalizado"),
        ],
        default="product",
        readonly=True,
        copy=False,
    )
    batch_size = fields.Integer(
        string="Tamaño de lote",
        default=200,
        required=True,
        help="Registros por fragmento. Valores bajos reducen picos de CPU/memoria.",
    )
    max_batches_per_cron = fields.Integer(
        string="Lotes máx. por ejecución de cron",
        default=2,
        required=True,
        help="Techo de lotes por vez que corre el cron (además del tope de segundos).",
    )
    max_cron_wallclock_seconds = fields.Integer(
        string="Máx. segundos de trabajo por ejecución de cron",
        default=20,
        required=True,
        help="El cron se detiene al cumplir este tiempo y continúa en la siguiente "
        "ejecución programada, para no monopolizar un worker.",
    )
    cron_commit_each_batch = fields.Boolean(
        string="Commit tras cada lote (solo cron)",
        default=True,
        help="Confirma cada lote en base de datos por separado: transacciones cortas, "
        "menos riesgo de bloqueos largos y menor pico de memoria en una sola transacción.",
    )
    include_product_images = fields.Boolean(
        string="Incluir image_128 en productos",
        default=False,
        help="Desactivado por defecto: evita leer binarios del filestore en catálogos grandes.",
    )
    build_cursor_product_id = fields.Integer(
        string="Último id de producto procesado",
        default=0,
        copy=False,
    )
    build_cursor_partner_id = fields.Integer(
        string="Último id de partner procesado",
        default=0,
        copy=False,
    )
    last_error = fields.Text(readonly=True, copy=False)
    last_ready_at = fields.Datetime(readonly=True, copy=False)
    chunk_ids = fields.One2many(
        "pos.bulk.catalog.chunk",
        "settings_id",
        string="Fragmentos",
    )
    chunk_count = fields.Integer(
        string="Nº fragmentos",
        compute="_compute_chunk_count",
    )

    _sql_constraints = [
        (
            "company_unique",
            "unique(company_id)",
            "Solo puede existir una configuración de caché masivo por compañía.",
        ),
    ]

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        """Expone en el formulario cuántos lotes se llevan sin abrir la pestaña."""
        for rec in self:
            rec.chunk_count = len(rec.chunk_ids)

    # -------------------------------------------------------------------------
    # Campos equivalentes al cargador estándar del POS (Odoo 17)
    # -------------------------------------------------------------------------
    def _base_product_field_names(self):
        """Lista de campos que el POS 17 pide por defecto para product.product."""
        names = [
            "id",
            "display_name",
            "lst_price",
            "standard_price",
            "categ_id",
            "pos_categ_ids",
            "taxes_id",
            "barcode",
            "default_code",
            "to_weight",
            "uom_id",
            "description_sale",
            "description",
            "product_tmpl_id",
            "tracking",
            "write_date",
            "available_in_pos",
            "attribute_line_ids",
            "active",
            "combo_ids",
            "product_tag_ids",
            "name",
            "detailed_type",
        ]
        if self.include_product_images:
            names.append("image_128")
        return names

    def _field_names_ensure_id(self, field_names):
        """Añade 'id' si falta: el cliente POS y módulos como pos_loyalty exigen p['id'] en cada dict."""
        names = list(field_names)
        if "id" in names:
            return names
        return ["id"] + names

    def _base_partner_field_names(self):
        """Campos estándar de res.partner en el POS."""
        return [
            "id",
            "name",
            "street",
            "city",
            "state_id",
            "country_id",
            "vat",
            "lang",
            "phone",
            "zip",
            "mobile",
            "email",
            "barcode",
            "write_date",
            "property_account_position_id",
            "property_product_pricelist",
            "parent_name",
        ]

    # -------------------------------------------------------------------------
    # Lectura del caché (usado por pos.config / pos.session)
    # -------------------------------------------------------------------------
    def _merged_rows(self, kind):
        """Une todos los fragmentos de un tipo en orden de sequence."""
        self.ensure_one()
        chunks = self.chunk_ids.filtered(lambda c: c.kind == kind).sorted("sequence")
        out = []
        for ch in chunks:
            out.extend(ch.decode_rows())
        return out

    def _iter_rows_from_chunks(self, kind):
        """Recorre filas fragmento a fragmento sin armar una lista gigante en RAM.

        Usado para la carga POS limitada: se puede salir en cuanto ya tenemos los ids buscados.
        """
        self.ensure_one()
        for ch in self.chunk_ids.filtered(lambda c: c.kind == kind).sorted("sequence"):
            for row in ch.decode_rows():
                yield row

    def get_products_for_fields(self, field_names):
        """Devuelve productos como lista de dicts filtrados a los campos pedidos."""
        self.ensure_one()
        if self.state != "ready":
            return None
        rows = self._merged_rows("product")
        if not rows:
            return []
        # Incluir siempre id aunque el loader no lo liste (extensiones y lógica POS lo usan).
        names = self._field_names_ensure_id(field_names)
        result = []
        for row in rows:
            result.append({fn: row.get(fn) for fn in names})
        return result

    def get_partners_for_fields(self, field_names):
        """Devuelve partners listos para el POS sin un segundo search_read."""
        self.ensure_one()
        if self.state != "ready":
            return None
        rows = self._merged_rows("partner")
        if not rows:
            return []
        names = self._field_names_ensure_id(field_names)
        return [{fn: row.get(fn) for fn in names} for row in rows]

    def get_products_for_limited_pos_load(self, pos_config, field_names):
        """Arma la lista de productos para la carga inicial igual que Odoo (ids limitados + combos).

        No devuelve todo el caché: solo los ids que `pos.config.get_limited_products_loading`
        usaría, leyendo filas del caché y completando huecos con search_read mínimo.
        """
        self.ensure_one()
        if self.state != "ready":
            return None
        if not self.chunk_ids.filtered(lambda c: c.kind == "product"):
            return None
        id_order = pos_config._get_limited_product_ids_expanded_for_pos_load()
        if not id_order:
            return []
        id_set = set(id_order)
        target = len(id_set)
        # Bloque: leer fragmentos en streaming y parar al tener todos los ids (evita decodificar todo el catálogo).
        by_id = {}
        for r in self._iter_rows_from_chunks("product"):
            rid = r.get("id")
            if rid in id_set:
                by_id[rid] = r
            if len(by_id) == target:
                break
        names = self._field_names_ensure_id(field_names)
        missing = []
        out = []
        # Bloque: una fila por id en el orden oficial (prioridad / límite del TPV).
        for pid in id_order:
            row = by_id.get(pid)
            if row is not None:
                out.append({fn: row.get(fn) for fn in names})
            else:
                missing.append(pid)
        # Bloque: variantes combo u otros ids no presentes en fragmentos cacheados.
        if missing:
            Product = self.env["product.product"].sudo()
            extra = Product.search_read(
                [("id", "in", missing)],
                fields=list(names),
            )
            extra_by_id = {r["id"]: r for r in extra}
            out = []
            for pid in id_order:
                row = by_id.get(pid)
                if row is not None:
                    out.append({fn: row.get(fn) for fn in names})
                elif pid in extra_by_id:
                    er = extra_by_id[pid]
                    out.append({fn: er.get(fn) for fn in names})
        return out

    def get_pricelist_items_raw(self):
        """Lista completa de ítems de tarifa cacheados (dicts search_read)."""
        self.ensure_one()
        if self.state != "ready":
            return None
        return self._merged_rows("pricelist_item")

    def get_merged_product_rows(self):
        """Productos con todas las claves guardadas (para dominios de tarifas)."""
        self.ensure_one()
        return self._merged_rows("product")

    # -------------------------------------------------------------------------
    # Construcción
    # -------------------------------------------------------------------------
    def _next_chunk_sequence(self, kind):
        self.ensure_one()
        last = self.env["pos.bulk.catalog.chunk"].search(
            [("settings_id", "=", self.id), ("kind", "=", kind)],
            order="sequence desc",
            limit=1,
        )
        return (last.sequence + 1) if last else 1

    def _append_chunk(self, kind, rows):
        """Comprime y guarda un lote como fragmento."""
        self.ensure_one()
        if not rows:
            return
        seq = self._next_chunk_sequence(kind)
        blob = gzip.compress(
            json.dumps(rows, default=date_utils.json_default).encode("utf-8")
        )
        self.env["pos.bulk.catalog.chunk"].create(
            {
                "settings_id": self.id,
                "kind": kind,
                "sequence": seq,
                "payload": base64.b64encode(blob),
            }
        )

    def _pos_session_for_processing(self):
        """Sesión POS usada para _process_pos_ui_product_product y dominios de tarifas."""
        self.ensure_one()
        ref = self.reference_pos_config_id
        session = self.env["pos.session"].sudo().search(
            [("config_id", "=", ref.id)], order="id desc", limit=1
        )
        return session

    def _build_product_step(self):
        """Procesa un lote de productos (keyset por id)."""
        self.ensure_one()
        ref = self.reference_pos_config_id
        Product = self.env["product.product"].sudo()
        domain = ref._get_available_product_domain()
        dom = expression.AND([domain, [("id", ">", self.build_cursor_product_id)]])
        products = Product.search(dom, order="id", limit=self.batch_size)
        if not products:
            # Fin de la fase productos: el dominio del TPV de referencia ya no devuelve filas tras el cursor.
            _logger.info(
                "pos_bulk_catalog: «%s» [id=%s] fase productos terminada (sin más filas) → "
                "siguiente fase: clientes",
                self.name,
                self.id,
            )
            self.write(
                {
                    "build_stage": "partner",
                    "build_cursor_product_id": 0,
                    "build_cursor_partner_id": 0,
                }
            )
            return False
        combo_products = products.filtered(lambda p: p.detailed_type == "combo")
        combo_extra = (
            combo_products.combo_ids.combo_line_ids.product_id.filtered("active")
        )
        all_products = products | combo_extra
        field_names = self._base_product_field_names()
        rows = all_products.read(field_names)
        session = self._pos_session_for_processing()
        if session:
            session._process_pos_ui_product_product(rows)
        else:
            _logger.warning(
                "pos_bulk_catalog: no hay pos.session para config %s; "
                "productos sin conversión de moneda/categoría POS estándar",
                ref.display_name,
            )
            self._apply_minimal_product_shape(ref, rows)
        self._append_chunk("product", rows)
        self.write({"build_cursor_product_id": max(products.ids)})
        return True

    def _apply_minimal_product_shape(self, ref, rows):
        """Si no hay sesión, asigna categ e image_128 como hace el POS."""
        session_new = self.env["pos.session"].new(
            {
                "config_id": ref.id,
                "user_id": self.env.user.id,
                "company_id": ref.company_id.id,
            }
        )
        try:
            params = session_new._loader_params_product_category()
            if ref.limit_categories and ref.iface_available_categ_ids:
                params["search_params"]["domain"] = [
                    ("id", "in", ref.iface_available_categ_ids.ids)
                ]
            categories = session_new._get_pos_ui_product_category(params)
            by_id = {c["id"]: c for c in categories}
            for product in rows:
                categ_tuple = product.get("categ_id")
                if categ_tuple:
                    product["categ"] = by_id.get(categ_tuple[0], {})
                product["image_128"] = bool(product.get("image_128"))
        except Exception as err:
            _logger.exception("pos_bulk_catalog: fallback categorías: %s", err)

    def _build_partner_step(self):
        """Un lote de clientes visibles para la compañía del TPV de referencia."""
        self.ensure_one()
        company = self.reference_pos_config_id.company_id
        Partner = self.env["res.partner"].sudo()
        dom = [
            "|",
            ("company_id", "=", company.id),
            ("company_id", "=", False),
        ]
        dom = expression.AND([dom, [("id", ">", self.build_cursor_partner_id)]])
        partners = Partner.search(dom, order="id", limit=self.batch_size)
        if not partners:
            _logger.info(
                "pos_bulk_catalog: «%s» [id=%s] fase clientes terminada → siguiente fase: "
                "tarifas (ítems de lista de precios; puede requerir tiempo suficiente en una corrida)",
                self.name,
                self.id,
            )
            self.write({"build_stage": "pricelist"})
            return False
        rows = partners.read(self._base_partner_field_names())
        self._append_chunk("partner", rows)
        self.write({"build_cursor_partner_id": max(partners.ids)})
        return True

    def _build_pricelist_once(self):
        """Genera todos los ítems de tarifa según productos ya cacheados."""
        self.ensure_one()
        products = self.get_merged_product_rows()
        ref = self.reference_pos_config_id
        session = self._pos_session_for_processing()
        if not session:
            session = self.env["pos.session"].new(
                {
                    "config_id": ref.id,
                    "user_id": self.env.user.id,
                    "company_id": ref.company_id.id,
                }
            )
        pricelists = self.env["product.pricelist"].sudo().search_read(
            **session._loader_params_product_pricelist()["search_params"]
        )
        if not products:
            self._append_chunk("pricelist_item", [])
            self.write(
                {
                    "build_stage": "done",
                    "state": "ready",
                    "last_ready_at": datetime.now(),
                }
            )
            _logger.info(
                "pos_bulk_catalog: «%s» [id=%s] estado LISTO (sin productos en caché; "
                "tarifas vacías). Fragmentos=%s | last_ready_at=%s",
                self.name,
                self.id,
                len(self.chunk_ids),
                self.last_ready_at,
            )
            return
        tmpl_ids = [p["product_tmpl_id"][0] for p in products if p.get("product_tmpl_id")]
        prod_ids = [p["id"] for p in products]
        domain = session._product_pricelist_item_domain_by_product(
            tmpl_ids, prod_ids, pricelists
        )
        fields_list = session._product_pricelist_item_fields()
        items = (
            self.env["product.pricelist.item"]
            .sudo()
            .search_read(domain, fields_list)
        )
        self._append_chunk("pricelist_item", items)
        self.write(
            {
                "build_stage": "done",
                "state": "ready",
                "last_ready_at": datetime.now(),
            }
        )
        _logger.info(
            "pos_bulk_catalog: «%s» [id=%s] estado LISTO — fase tarifas completada | "
            "productos en caché=%s | ítems tarifa=%s | fragmentos=%s | last_ready_at=%s",
            self.name,
            self.id,
            len(products),
            len(items),
            len(self.chunk_ids),
            self.last_ready_at,
        )

    def _cron_should_stop(self, t0_mono, max_seconds, reserve_for_pricelist=False):
        """Devuelve True si hay que ceder el worker (tope de tiempo blando)."""
        if not max_seconds or max_seconds <= 0:
            return False
        elapsed = time.monotonic() - t0_mono
        limit = max_seconds
        if reserve_for_pricelist:
            limit = max(1.0, max_seconds - 5.0)
        return elapsed >= limit

    def _commit_batch_if_needed(self, commit_each_batch):
        """Confirma la transacción y renueva el recordset tras un lote (uso cron)."""
        if not commit_each_batch:
            return self
        rid = self.id
        self.env.flush_all()
        self.env.cr.commit()
        return self.env["pos.bulk.catalog.settings"].browse(rid)

    def _log_build_pending_summary(self):
        """Registra cuánto falta (aprox.) por fase: un search_count según dominio actual.

        Se llama al cerrar una ronda de `process_build_batches` si sigue en «building».
        Útil para ver en logs del cron el progreso hacia estado Listo.
        """
        self.ensure_one()
        if self.state != "building":
            return
        ref = self.reference_pos_config_id
        # Bloque: estimación de productos pendientes (id mayor que cursor y dominio TPV).
        if self.build_stage == "product":
            Product = self.env["product.product"].sudo()
            domain = ref._get_available_product_domain()
            dom = expression.AND([domain, [("id", ">", self.build_cursor_product_id)]])
            pending = Product.search_count(dom)
            _logger.info(
                "pos_bulk_catalog: pendiente → «%s» [id=%s] fase productos: ~%s registros "
                "por delante (cursor id > %s) | fragmentos=%s",
                self.name,
                self.id,
                pending,
                self.build_cursor_product_id,
                len(self.chunk_ids),
            )
            return
        # Bloque: estimación de clientes pendientes.
        if self.build_stage == "partner":
            company = ref.company_id
            Partner = self.env["res.partner"].sudo()
            dom = [
                "|",
                ("company_id", "=", company.id),
                ("company_id", "=", False),
            ]
            dom = expression.AND([dom, [("id", ">", self.build_cursor_partner_id)]])
            pending = Partner.search_count(dom)
            _logger.info(
                "pos_bulk_catalog: pendiente → «%s» [id=%s] fase clientes: ~%s registros "
                "por delante (cursor id > %s) | fragmentos=%s",
                self.name,
                self.id,
                pending,
                self.build_cursor_partner_id,
                len(self.chunk_ids),
            )
            return
        # Bloque: fase tarifas — no hay cursor; el siguiente paso completa y marca Listo.
        if self.build_stage == "pricelist":
            _logger.info(
                "pos_bulk_catalog: pendiente → «%s» [id=%s] fase tarifas: falta una corrida "
                "con tiempo suficiente (max_cron_wallclock_seconds) para generar ítems y "
                "pasar a Listo (sin contador numérico de pendientes)",
                self.name,
                self.id,
            )

    def process_build_batches(
        self,
        commit_each_batch=False,
        max_wallclock_seconds=None,
    ):
        """Ejecuta lotes hasta agotar tope de cantidad o de tiempo.

        :param commit_each_batch: si True, hace commit tras cada lote (recomendado en cron).
        :param max_wallclock_seconds: tope blando en segundos; None = sin tope por tiempo.
        """
        self.ensure_one()
        if self.state != "building":
            return
        if self.build_stage == "done":
            return
        max_b = max(1, self.max_batches_per_cron)
        if max_wallclock_seconds is None and commit_each_batch:
            max_wallclock_seconds = self.max_cron_wallclock_seconds
        t0 = time.monotonic()
        done_steps = 0
        # Entrada a la ronda (cron o primer clic): deja trazabilidad en log.
        _logger.info(
            "pos_bulk_catalog: ronda construcción «%s» [id=%s] | fase=%s | estado=%s | "
            "max_lotes=%s | tope_segundos=%s | commit_por_lote=%s | cursor_prod>%s | cursor_partner>%s",
            self.name,
            self.id,
            self.build_stage,
            self.state,
            max_b,
            max_wallclock_seconds,
            commit_each_batch,
            self.build_cursor_product_id,
            self.build_cursor_partner_id,
        )
        try:
            while done_steps < max_b:
                if self._cron_should_stop(t0, max_wallclock_seconds):
                    _logger.info(
                        "pos_bulk_catalog: tope de tiempo (%ss) para %s; "
                        "siguiente ejecución del cron continuará",
                        max_wallclock_seconds,
                        self.display_name,
                    )
                    break
                if self.build_stage == "pricelist" and self._cron_should_stop(
                    t0, max_wallclock_seconds, reserve_for_pricelist=True
                ):
                    _logger.info(
                        "pos_bulk_catalog: tiempo insuficiente para fase tarifas; "
                        "se difiere a la siguiente corrida del cron (%s)",
                        self.display_name,
                    )
                    break
                if self.build_stage == "product":
                    if not self._build_product_step():
                        continue
                elif self.build_stage == "partner":
                    if not self._build_partner_step():
                        continue
                elif self.build_stage == "pricelist":
                    self._build_pricelist_once()
                    break
                else:
                    break
                done_steps += 1
                self = self._commit_batch_if_needed(commit_each_batch)
                # Un lote escrito (productos o clientes): estado tras commit.
                _logger.info(
                    "pos_bulk_catalog: lote guardado «%s» [id=%s] | lote %s/%s | fase=%s | "
                    "cursor_prod último=%s | cursor_partner último=%s | fragmentos=%s",
                    self.name,
                    self.id,
                    done_steps,
                    max_b,
                    self.build_stage,
                    self.build_cursor_product_id,
                    self.build_cursor_partner_id,
                    len(self.chunk_ids),
                )
                if self.build_stage == "done":
                    break
            # Resumen al salir del bucle: pendiente hacia Listo (el paso a Listo ya se loguea en _build_pricelist_once).
            fresh = self.browse(self.id)
            if fresh.state == "building":
                fresh._log_build_pending_summary()
        except Exception as err:
            _logger.exception("pos_bulk_catalog build error")
            self.write(
                {
                    "state": "error",
                    "last_error": repr(err),
                }
            )

    @api.model
    def cron_continue_build(self):
        """Cron: una sola ejecución global con lock; lotes pequeños y commits cortos.

        Desactivación global: parámetro ``pos_bulk_catalog.cron_master_disabled`` = true.
        """
        icp = self.env["ir.config_parameter"].sudo()
        if icp.get_param("pos_bulk_catalog.cron_master_disabled", "False").lower() in (
            "1",
            "true",
            "yes",
        ):
            return
        cr = self.env.cr
        cr.execute("SELECT pg_try_advisory_lock(%s)", (_PG_ADVISORY_LOCK_POS_BULK,))
        got_lock = cr.fetchone()[0]
        if not got_lock:
            _logger.info(
                "pos_bulk_catalog: cron omitido (lock ocupado: otro worker o ejecución en curso)"
            )
            return
        try:
            to_run = self.search([("state", "=", "building")], order="id")
            if not to_run:
                _logger.info(
                    "pos_bulk_catalog: cron «continuar construcción» ejecutado — "
                    "no hay cachés en estado building (nada que hacer)"
                )
            else:
                _logger.info(
                    "pos_bulk_catalog: cron «continuar construcción» — %s caché(s) en building: %s",
                    len(to_run),
                    ", ".join(f"«{r.name}»[id={r.id}] fase={r.build_stage}" for r in to_run),
                )
            for rec in to_run:
                rec.process_build_batches(
                    commit_each_batch=rec.cron_commit_each_batch,
                    max_wallclock_seconds=rec.max_cron_wallclock_seconds,
                )
                done = self.env["pos.bulk.catalog.settings"].browse(rec.id)
                _logger.info(
                    "pos_bulk_catalog: cron — tras procesar «%s» [id=%s] → estado=%s | fase=%s | "
                    "fragmentos=%s",
                    done.name,
                    done.id,
                    done.state,
                    done.build_stage,
                    len(done.chunk_ids),
                )
        finally:
            cr.execute("SELECT pg_advisory_unlock(%s)", (_PG_ADVISORY_LOCK_POS_BULK,))

    def action_start_build(self):
        """Encola construcción: borra fragmentos previos y deja el cron continuar."""
        for rec in self:
            if not rec.reference_pos_config_id:
                raise UserError(_("Indique un punto de venta de referencia."))
            rec.chunk_ids.unlink()
            rec.write(
                {
                    "state": "building",
                    "build_stage": "product",
                    "build_cursor_product_id": 0,
                    "build_cursor_partner_id": 0,
                    "last_error": False,
                }
            )
        # Primera pasada acotada en la misma petición HTTP (sin commits intermedios).
        for rec in self:
            rec.process_build_batches(
                commit_each_batch=False,
                max_wallclock_seconds=min(15, rec.max_cron_wallclock_seconds),
            )
        # Odoo no refresca el formulario solo con una notificación: hay que reabrir el
        # registro para ver estado, fase y fragmentos actualizados.
        self.invalidate_recordset()
        if len(self) == 1:
            fresh = self.browse(self.id)
            n = len(fresh.chunk_ids)
            state_lbl = {
                "draft": _("Borrador"),
                "building": _("Construyendo"),
                "ready": _("Listo"),
                "error": _("Error"),
            }.get(fresh.state, fresh.state)
            stage_lbl = {
                "product": _("Productos"),
                "partner": _("Clientes"),
                "pricelist": _("Tarifas"),
                "done": _("Finalizado"),
            }.get(fresh.build_stage, fresh.build_stage)
            msg = _(
                "Primera pasada hecha: estado «%(state)s», fase «%(stage)s», "
                "%(n)s fragmento(s). Si no termina solo, active el cron planificado "
                "(Ajustes técnicos → Automatización)."
            ) % {"state": state_lbl, "stage": stage_lbl, "n": n}
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Caché POS"),
                    "message": msg,
                    "type": "success",
                    "sticky": True,
                    "next": {
                        "type": "ir.actions.act_window",
                        "name": fresh.display_name,
                        "res_model": self._name,
                        "res_id": fresh.id,
                        "view_mode": "form",
                        "views": [(False, "form")],
                        "target": "current",
                    },
                },
            }
        return True

    def action_reset_draft(self):
        self.write({"state": "draft", "build_stage": "product", "last_error": False})
        self.invalidate_recordset()
        if len(self) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": self.display_name,
                "res_model": self._name,
                "res_id": self.id,
                "view_mode": "form",
                "views": [(False, "form")],
                "target": "current",
            }
        return True

    @api.constrains("reference_pos_config_id", "company_id")
    def _check_reference_config_company(self):
        for rec in self:
            if (
                rec.reference_pos_config_id
                and rec.reference_pos_config_id.company_id != rec.company_id
            ):
                raise ValidationError(
                    _("El TPV de referencia debe ser de la misma compañía que la configuración.")
                )

    @api.constrains(
        "max_cron_wallclock_seconds", "batch_size", "max_batches_per_cron"
    )
    def _check_cron_safety_limits(self):
        for rec in self:
            if rec.batch_size < 1:
                raise ValidationError(_("El tamaño de lote debe ser al menos 1."))
            if rec.max_batches_per_cron < 1:
                raise ValidationError(_("Los lotes por cron deben ser al menos 1."))
            if rec.max_cron_wallclock_seconds < 5:
                raise ValidationError(
                    _("El tope de segundos del cron debe ser al menos 5 (evita bucles inútiles).")
                )
