# -*- coding: utf-8 -*-

import json
import logging

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FenicioCatalogLine(models.Model):
    _name = 'fenicio.catalog.line'
    _description = 'Catálogo Fenicio — una línea por variante/presentación'
    _order = 'producto_nombre, variante_nombre, presentacion_nombre'

    # ── Datos del producto padre ─────────────────────────────────────────────
    producto_codigo = fields.Char('Código Producto')
    producto_nombre = fields.Char('Producto')
    fecha_creacion = fields.Char('Fecha Creación')
    prioridad = fields.Integer('Prioridad')
    moneda = fields.Char('Moneda', default='UYU')
    impuesto = fields.Float('Impuesto %')
    atributos_producto = fields.Text('Atributos Producto')
    categoria_fenicio_id = fields.Char('ID Categoría Fenicio')
    categoria_fenicio_nombre = fields.Char('Categoría Fenicio')
    marca_fenicio_id = fields.Char('ID Marca Fenicio')
    marca_fenicio_nombre = fields.Char('Marca Fenicio')

    # ── Datos de la variante ─────────────────────────────────────────────────
    variante_codigo = fields.Char('Código Variante')
    variante_nombre = fields.Char('Variante')
    atributos_variante = fields.Text('Atributos Variante')
    variante_descripcion = fields.Text('Descripción Variante')

    # ── Datos de la presentación (clave única) ───────────────────────────────
    presentacion_codigo = fields.Char('Código Presentación', required=True)
    presentacion_nombre = fields.Char('Presentación')
    sku = fields.Char('SKU')
    stock = fields.Integer('Stock')
    precio_lista = fields.Float('Precio Lista', digits=(12, 2))
    precio_venta = fields.Float('Precio Venta', digits=(12, 2))
    precio_alternativo = fields.Float('Precio Alternativo', digits=(12, 2))

    # ── Vínculo Odoo ─────────────────────────────────────────────────────────
    odoo_product_id = fields.Many2one(
        'product.product', 'Producto Odoo', ondelete='set null', readonly=True
    )
    ultima_sincronizacion = fields.Datetime('Última Sincronización', readonly=True)

    _sql_constraints = [
        ('sku_unique', 'unique(sku)',
         'El SKU ya existe en el catálogo.'),
    ]

    # ── Helpers de acceso a la API ───────────────────────────────────────────

    @api.model
    def _get_catalog_url(self):
        website = self.env['website'].search(
            [('company_id', '=', self.env.company.id)], limit=1
        )
        if not website:
            website = self.env['website'].search([], limit=1)
        base_url = website.fenicio_catalog_url if website else False
        if not base_url:
            raise UserError(
                'No hay una URL de catálogo configurada. '
                'Ingresá la URL base en el sitio web → pestaña Fenicio.'
            )
        return base_url.rstrip('/') + '/API_V1/catalogo'

    @api.model
    def _fetch_catalog(self, url):
        """Descarga el catálogo desde Fenicio.

        Args:
            url (str): endpoint del catálogo Fenicio.

        Returns:
            tuple[str, dict | list]: el cuerpo crudo de la respuesta tal cual
                lo devuelve el endpoint, y el mismo cuerpo ya parseado a JSON.

        Raises:
            UserError: si falla la conexión, hay timeout, el endpoint
                devuelve un error HTTP o el cuerpo no es JSON válido.
        """
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise UserError(f'No se pudo conectar a Fenicio: {url}')
        except requests.exceptions.Timeout:
            raise UserError('La solicitud a Fenicio tardó demasiado (timeout 60s).')
        except requests.exceptions.HTTPError as e:
            raise UserError(f'Fenicio devolvió un error HTTP: {e}')
        try:
            return resp.json()
        except ValueError:
            raise UserError('La respuesta de Fenicio no es JSON válido.')

    @api.model
    def _extract_products(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if data.get('error'):
                raise UserError(f"Fenicio devolvió un error: {data.get('msj') or 'sin detalle'}")
            if isinstance(data.get('productos'), list):
                return data['productos']
            for v in data.values():
                if isinstance(v, list) and v:
                    return v
            for v in data.values():
                if isinstance(v, dict):
                    try:
                        return self._extract_products(v)
                    except Exception:
                        continue
            raise UserError(
                'No se encontró una lista de productos en la respuesta de Fenicio.\n'
                f'Claves recibidas: {list(data.keys())}'
            )
        raise UserError('Formato de respuesta inesperado desde Fenicio.')

    @api.model
    def _iter_lines(self, products):
        """Yield un dict por presentación aplanando producto → variante → presentación.

        Mapea los nombres de campo abreviados que usa la API real de Fenicio
        (cod/nom/vars/pres/pr_lista/pr_promo) a los campos del modelo. No hay
        equivalente de precio alternativo en la respuesta, así que queda en 0.
        """
        now = fields.Datetime.now()
        for prod in products:
            moneda = prod.get('moneda') or 'UYU'
            categ = prod.get('categ') or {}
            marca = prod.get('marca') or {}
            prod_base = {
                'producto_codigo': prod.get('cod'),
                'producto_nombre': prod.get('nom'),
                'moneda': moneda,
                'atributos_producto': json.dumps(
                    prod.get('caracts') or {}, ensure_ascii=False
                ),
                'categoria_fenicio_id': str(categ.get('id')) if categ.get('id') is not None else False,
                'categoria_fenicio_nombre': categ.get('nom'),
                'marca_fenicio_id': str(marca.get('id')) if marca.get('id') is not None else False,
                'marca_fenicio_nombre': marca.get('nom'),
                'ultima_sincronizacion': now,
            }
            for variant in (prod.get('vars') or []):
                var_base = {
                    'variante_codigo': variant.get('cod'),
                    'variante_nombre': variant.get('nom'),
                    'atributos_variante': json.dumps(
                        variant.get('caracts') or {}, ensure_ascii=False
                    ),
                    'variante_descripcion': variant.get('desc') or False,
                }
                for pres in (variant.get('pres') or []):

                    def _price(d):
                        if not isinstance(d, dict):
                            return 0.0
                        return float(d.get(moneda) or next(iter(d.values()), 0) or 0)

                    yield {
                        **prod_base,
                        **var_base,
                        'presentacion_codigo': pres.get('cod'),
                        'presentacion_nombre': pres.get('nom'),
                        'sku': pres.get('sku'),
                        'stock': int(pres.get('stock') or 0),
                        'precio_lista': _price(pres.get('pr_lista')),
                        'precio_venta': _price(pres.get('pr_promo')),
                        'precio_alternativo': 0.0,
                    }

    # ── Feature 1: sincronizar desde Fenicio ────────────────────────────────

    @api.model
    def action_sync_all(self):
        url = self._get_catalog_url()
        _logger.info('[Fenicio] Sincronizando catálogo desde %s', url)
        data = self._fetch_catalog(url)
        products = self._extract_products(data)

        created = updated = skipped = 0
        for vals in self._iter_lines(products):
            sku = vals.get('sku')
            if not sku:
                skipped += 1
                continue
            existing = self.search([('sku', '=', sku)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.create(vals)
                created += 1

        _logger.info(
            '[Fenicio] Sync completado: %d creados, %d actualizados, %d sin código',
            created, updated, skipped,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sincronización completada',
                'message': f'{created} líneas creadas, {updated} actualizadas.',
                'type': 'success',
                'sticky': False,
            },
        }

    # ── Feature 2: actualizar campos Fenicio en product.product ─────────────

    @api.model
    def action_update_odoo_products(self):
        lines = self.search([('sku', '!=', False)])
        ProductProduct = self.env['product.product']
        Currency = self.env['res.currency']
        updated = skipped = 0

        for line in lines:
            product = ProductProduct.search(
                [('default_code', '=', line.sku)], limit=1
            )
            if not product:
                skipped += 1
                continue

            moneda_rec = Currency.search([('name', '=', line.moneda)], limit=1)

            # Precio de venta Fenicio
            product.fenicio_precio_venta = line.precio_venta
            # Precio de lista Fenicio
            product.fenicio_precio_lista = line.precio_lista
            # Precio alternativo Fenicio
            product.fenicio_precio_alternativo = line.precio_alternativo


            # Precios lista/venta Fenicio (fenicio.presentacion.price)
            product.precios_fenicio_ids = [(5, 0, 0)]
            price_vals = []
            if line.precio_lista and moneda_rec:
                price_vals.append((0, 0, {
                    'price_type': 'precioLista',
                    'currency_id': moneda_rec.id,
                    'price': line.precio_lista,
                }))
            if line.precio_venta and moneda_rec:
                price_vals.append((0, 0, {
                    'price_type': 'precioVenta',
                    'currency_id': moneda_rec.id,
                    'price': line.precio_venta,
                }))
            if price_vals:
                product.precios_fenicio_ids = price_vals

            # Precio alternativo (precios.alternativos → fenicio.presentacion.price)
            if line.precio_alternativo and moneda_rec:
                product.precios_alternativos_fenicio_ids = [(5, 0, 0)]
                alt = self.env['precios.alternativos'].create({
                    'product_id': product.id,
                    'code': line.presentacion_codigo or '',
                })
                self.env['fenicio.presentacion.price'].create({
                    'alternative_price_id': alt.id,
                    'price_type': 'precioVenta',
                    'currency_id': moneda_rec.id,
                    'price': line.precio_alternativo,
                })

            line.odoo_product_id = product.id
            updated += 1

        _logger.info(
            '[Fenicio] Actualización completada: %d actualizados, %d sin SKU en Odoo',
            updated, skipped,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Actualización completada',
                'message': f'{updated} productos actualizados, {skipped} SKUs no encontrados en Odoo.',
                'type': 'success' if skipped == 0 else 'warning',
                'sticky': False,
            },
        }
