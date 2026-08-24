# -*- coding: utf-8 -*-

import json
import logging
import unicodedata

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FenicioCatalogSync(models.TransientModel):
    _name = 'fenicio.catalog.sync'
    _description = 'Sincronizar Catálogo Fenicio'

    total_creados = fields.Integer('Líneas creadas', readonly=True)
    total_actualizados = fields.Integer('Líneas actualizadas', readonly=True)
    total_odoo = fields.Integer('Productos Odoo actualizados', readonly=True)
    not_found_line_ids = fields.Many2many(
        'fenicio.catalog.line',
        'fenicio_catalog_sync_notfound_rel',
        'sync_id',
        'line_id',
        string='SKUs no encontrados en Odoo',
        readonly=True,
    )
    test_json = fields.Text(
        string='JSON de prueba',
        default=lambda self: json.dumps(
            self.env['fenicio.catalog.export']._SAMPLE_JSON,
            indent=2,
            ensure_ascii=False,
        ),
    )
    state = fields.Selection(
        [('draft', 'Listo'), ('done', 'Completado')],
        default='draft',
    )

    def _get_website(self):
        """Devuelve el website del contexto (abierto desde la vista de website) o busca el de la compañía."""
        website_id = self.env.context.get('default_website_id') or self.env.context.get('active_id')
        if website_id and self.env.context.get('active_model') in ('website', None):
            website = self.env['website'].browse(website_id).exists()
            if website:
                return website
        return (
            self.env['website'].search([('company_id', '=', self.env.company.id)], limit=1)
            or self.env['website'].search([], limit=1)
        )

    def _self_action(self):
        """Retorna la acción para reabrir el mismo wizard conservando el contexto."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_sync(self):
        self.ensure_one()
        CatalogLine = self.env['fenicio.catalog.line']
        website = self._get_website()
        if not website or not website.fenicio_catalog_url:
            raise UserError('No hay una URL de catálogo configurada en el sitio web.')
        url = website.fenicio_catalog_url.rstrip('/') + '/API_V1/catalogo'
        data = CatalogLine._fetch_catalog(url)
        products = CatalogLine._extract_products(data)
        _logger.info("Catálogo Fenicio obtenido desde %s: %d productos", url, len(products))

        created = updated = skipped = 0
        for vals in CatalogLine._iter_lines(products):
            sku = vals.get('sku')
            if not sku:
                skipped += 1
                continue
            existing = CatalogLine.search([('sku', '=', sku)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                CatalogLine.create(vals)
                created += 1

        self.write({'total_creados': created, 'total_actualizados': updated, 'state': 'done'})
        self.env['fenicio.log'].registrar(
            estado='ok',
            endpoint=url,
            request=(
                f'Sincronización automática desde Fenicio — '
                f'{created} líneas creadas, {updated} actualizadas, {skipped} sin SKU.'
            ),
            mensaje=data,
        )
        return self._self_action()

    def _upsert_pricelist_item(self, pricelist, product, price):
        if not pricelist or not price:
            return
        Item = self.env['product.pricelist.item']
        item = Item.search([
            ('pricelist_id', '=', pricelist.id),
            ('product_id', '=', product.id),
            ('applied_on', '=', '0_product_variant'),
        ], limit=1)
        vals = {'compute_price': 'fixed', 'fixed_price': price}
        if item:
            item.write(vals)
        else:
            Item.create({**vals, 'pricelist_id': pricelist.id, 'product_id': product.id, 'applied_on': '0_product_variant'})

    # ── Helpers de mapeo Fenicio → Odoo (categoría/marca/atributos) ─────────

    @staticmethod
    def _normalize(text):
        """Nombre en mayúsculas sin acentos, para comparar sin depender del idioma."""
        if not text:
            return ''
        text = unicodedata.normalize('NFKD', str(text))
        return text.encode('ascii', 'ignore').decode('ascii').strip().upper()

    def _get_or_create_category(self, fenicio_id, nombre):
        Category = self.env['product.public.category']
        if fenicio_id:
            category = Category.search([('fenicio_code', '=', fenicio_id)], limit=1)
            if category:
                return category
        if not nombre:
            return Category
        norm = self._normalize(nombre)
        for candidate in Category.search([('name', 'ilike', nombre)]):
            if self._normalize(candidate.name) == norm:
                if fenicio_id and not candidate.fenicio_code:
                    candidate.fenicio_code = fenicio_id
                return candidate
        return Category.create({'name': nombre, 'fenicio_code': fenicio_id or False})

    def _get_or_create_brand(self, fenicio_id, nombre):
        Brand = self.env['product.brand']
        if fenicio_id:
            brand = Brand.search([('fenicio_brand_id', '=', fenicio_id)], limit=1)
            if brand:
                return brand
        if not nombre:
            return Brand
        norm = self._normalize(nombre)
        for candidate in Brand.search([('name', 'ilike', nombre)]):
            if self._normalize(candidate.name) == norm:
                if fenicio_id and not candidate.fenicio_brand_id:
                    candidate.fenicio_brand_id = fenicio_id
                return candidate
        return Brand.create({'name': nombre, 'fenicio_brand_id': fenicio_id or False})

    def _get_color_attribute(self):
        """Atributo usado para el nivel 'vars' (color) de Fenicio.

        Usa el primer atributo marcado fenicio_type='variante'; si ninguno lo está,
        cae de vuelta al atributo llamado "Color" y lo marca para las próximas veces.
        """
        Attribute = self.env['product.attribute']
        attribute = Attribute.search([('fenicio_type', '=', 'variante')], limit=1)
        if attribute:
            return attribute
        for candidate in Attribute.search([('name', 'ilike', 'color')]):
            if self._normalize(candidate.name) == 'COLOR':
                candidate.fenicio_type = 'variante'
                return candidate
        raise UserError(
            'No hay un atributo de Color configurado para mapear las variantes de Fenicio. '
            'Creá un atributo "Color" o marcá uno existente con Tipo Fenicio = Variante.'
        )

    def _get_or_create_attribute_value(self, attribute, codigo, nombre):
        norm = self._normalize(nombre)
        for candidate in attribute.value_ids:
            if self._normalize(candidate.name) == norm:
                if codigo and not candidate.fenicio_attribute_value_code:
                    candidate.fenicio_attribute_value_code = codigo
                return candidate
        return self.env['product.attribute.value'].create({
            'name': nombre or codigo,
            'attribute_id': attribute.id,
            'fenicio_attribute_value_code': codigo or False,
        })

    def _apply_product_settings(self, template, atributos_json):
        """Mapea las características a nivel producto (caracts) a product.setting,
        matcheando por convención de nombre 'Fenicio_<Clave>'. No crea atributos nuevos."""
        if not atributos_json:
            return
        try:
            caracts = json.loads(atributos_json)
        except (TypeError, ValueError):
            return
        if not isinstance(caracts, dict) or not caracts:
            return

        fenicio_attrs = self.env['product.attribute'].search([('name', 'like', 'Fenicio_')])
        attrs_by_key = {
            self._normalize(attr.name).replace('FENICIO_', '', 1): attr
            for attr in fenicio_attrs
        }

        Setting = self.env['product.setting']
        for clave, valor in caracts.items():
            if not valor:
                continue
            attribute = attrs_by_key.get(self._normalize(clave))
            if not attribute:
                continue
            value = self._get_or_create_attribute_value(attribute, False, str(valor))
            setting = Setting.search([
                ('product_template_id', '=', template.id),
                ('attribute_id', '=', attribute.id),
            ], limit=1)
            if setting:
                if setting.value_id != value:
                    setting.value_id = value.id
            else:
                Setting.create({
                    'product_template_id': template.id,
                    'attribute_id': attribute.id,
                    'value_id': value.id,
                })

    def action_update_odoo(self):
        self.ensure_one()
        lines = self.env['fenicio.catalog.line'].search([('sku', '!=', False)])
        website = self._get_website()
        updated = 0
        not_found = self.env['fenicio.catalog.line']

        for line in lines:
            product = self.env['product.product'].search([('default_code', '=', line.sku)], limit=1)
            if not product:
                not_found |= line
                continue
            template = product.product_tmpl_id
            if not template.product_e_fenicio:
                template.product_e_fenicio = True

            category = self._get_or_create_category(line.categoria_fenicio_id, line.categoria_fenicio_nombre)
            brand = self._get_or_create_brand(line.marca_fenicio_id, line.marca_fenicio_nombre)
            tmpl_vals = {}
            if category and category not in template.public_categ_ids:
                tmpl_vals['public_categ_ids'] = [(4, category.id)]
            if brand and template.product_brand_id != brand:
                tmpl_vals['product_brand_id'] = brand.id
            if tmpl_vals:
                template.write(tmpl_vals)
            self._apply_product_settings(template, line.atributos_producto)

            product.write({
                'fenicio_precio_venta': line.precio_venta,
                'fenicio_precio_lista': line.precio_lista,
                'fenicio_precio_alternativo': line.precio_alternativo,
            })
            self._upsert_pricelist_item(website.fenicio_pricelist_venta_id, product, line.precio_venta)
            self._upsert_pricelist_item(website.fenicio_pricelist_lista_id, product, line.precio_lista)
            self._upsert_pricelist_item(website.fenicio_pricelist_alternativo_id, product, line.precio_alternativo)
            line.odoo_product_id = product.id
            updated += 1

        self.write({'total_odoo': updated, 'not_found_line_ids': [(6, 0, not_found.ids)], 'state': 'done'})
        return self._self_action()

    def _get_talle_attribute_for_category(self, category):
        """Atributo Talle a usar para esta categoría: el que tenga configurado en
        product.attribute.fenicio_categoria_ids, o si ninguno matchea, el atributo
        marcado como Talle Fenicio por defecto (fenicio_talle_default)."""
        Attribute = self.env['product.attribute']
        if category:
            attribute = Attribute.search([('fenicio_categoria_ids', 'in', category.id)], limit=1)
            if attribute:
                return attribute
        return Attribute.search([('fenicio_talle_default', '=', True)], limit=1)

    def _set_attribute_line(self, template, attribute, value_ids):
        """Crea o completa la línea de atributo del template con estos valores,
        sin sacar los que ya estaban (no borra combinaciones existentes)."""
        attr_line = template.attribute_line_ids.filtered(lambda l: l.attribute_id == attribute)
        if attr_line:
            attr_line.value_ids = [(4, vid) for vid in value_ids]
        else:
            template.attribute_line_ids = [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, value_ids)],
            })]

    def action_create_missing(self):
        """Crea un product.template por producto Fenicio (no por línea), con una
        variante por color. Si un producto tiene más de una presentación real por
        variante (talle/tamaño), se usa el atributo Talle que tenga la categoría del
        producto en su product.attribute.fenicio_categoria_ids; si ninguno matchea
        esa categoría, se usa el atributo marcado fenicio_talle_default (Talle
        Fenicio por defecto); si tampoco hay uno marcado, se salta y se loguea para
        revisión manual en vez de adivinar cuál usar."""
        self.ensure_one()
        color_attr = self._get_color_attribute()
        Line = self.env['fenicio.catalog.line']
        created = 0
        skipped_lines = Line

        groups = {}
        for line in self.not_found_line_ids:
            if not line.producto_codigo:
                skipped_lines |= line
                continue
            groups.setdefault(line.producto_codigo, Line)
            groups[line.producto_codigo] |= line

        for producto_codigo, lines in groups.items():
            try:
                first = lines[:1]
                category = self._get_or_create_category(
                    first.categoria_fenicio_id, first.categoria_fenicio_nombre
                )
                brand = self._get_or_create_brand(first.marca_fenicio_id, first.marca_fenicio_nombre)

                by_variant = {}
                for line in lines:
                    by_variant.setdefault(line.variante_codigo, Line)
                    by_variant[line.variante_codigo] |= line
                necesita_talle = any(len(sub) > 1 for sub in by_variant.values())

                talle_attr = False
                if necesita_talle:
                    talle_attr = self._get_talle_attribute_for_category(category)
                    if not talle_attr:
                        skipped_lines |= lines
                        self.env['fenicio.log'].registrar(
                            estado='error',
                            endpoint='action_create_missing',
                            request=(
                                f'Producto Fenicio {producto_codigo}: tiene más de una '
                                'presentación real por variante (talle/tamaño), ningún '
                                'atributo tiene configurada la categoría '
                                f'"{category.name if category else "(sin categoría)"}" en '
                                'Categorías Talle Fenicio, y no hay ningún atributo marcado '
                                'como Talle Fenicio por defecto (formulario de Atributo de '
                                'producto). Configurá alguno de los dos para poder importar '
                                'este producto.'
                            ),
                        )
                        continue
                    if category and category not in talle_attr.fenicio_categoria_ids:
                        _logger.info(
                            "[Fenicio] Producto %s: categoría '%s' sin atributo Talle propio, "
                            "se usa el default '%s'.",
                            producto_codigo,
                            category.name if category else '(sin categoría)',
                            talle_attr.name,
                        )
                    if talle_attr.fenicio_type != 'presentacion':
                        talle_attr.fenicio_type = 'presentacion'

                template = self.env['product.template'].search(
                    [('code_e_fenicio', '=', producto_codigo)], limit=1
                )
                if not template:
                    template = self.env['product.template'].create({
                        'name': first.producto_nombre or producto_codigo,
                        'product_e_fenicio': True,
                        'code_e_fenicio': producto_codigo,
                        'type': 'consu',
                    })

                tmpl_vals = {}
                if category and category not in template.public_categ_ids:
                    tmpl_vals['public_categ_ids'] = [(4, category.id)]
                if brand and template.product_brand_id != brand:
                    tmpl_vals['product_brand_id'] = brand.id
                descripcion = next((l.variante_descripcion for l in lines if l.variante_descripcion), False)
                if descripcion and not template.descripcion_fenicio:
                    tmpl_vals['descripcion_fenicio'] = descripcion
                if tmpl_vals:
                    template.write(tmpl_vals)

                dimensiones_esperadas = color_attr | talle_attr if talle_attr else color_attr
                otras_dimensiones = template.attribute_line_ids.attribute_id - dimensiones_esperadas
                if otras_dimensiones:
                    # El producto Odoo ya existente tiene otra dimensión de variante que
                    # esta sincronización no gestiona (ej. "Color Secundario"). No se
                    # tocan sus variantes para no matchear/archivar de forma ambigua.
                    skipped_lines |= lines
                    self.env['fenicio.log'].registrar(
                        estado='error',
                        endpoint='action_create_missing',
                        request=(
                            f'Producto Fenicio {producto_codigo}: el producto Odoo '
                            f'"{template.display_name}" ya tiene otra dimensión de '
                            f'variante ({", ".join(otras_dimensiones.mapped("name"))}) que '
                            'esta sincronización no gestiona. Se salta para no generar ni '
                            'archivar variantes de forma ambigua; requiere revisión manual.'
                        ),
                    )
                    continue

                # Variantes que ya existían ANTES de tocar attribute_line_ids: nunca se
                # archivan, tengan o no otras dimensiones de atributo que este código no
                # conoce (ej. una tercera dimensión tipo "Color Secundario" ya configurada
                # a mano). Solo se archivan combinaciones nuevas que genera Odoo como
                # resultado de agregar valores y que no corresponden a ningún SKU real.
                existing_variant_ids = set(template.product_variant_ids.ids)

                color_value_ids = []
                talle_value_ids = []
                line_by_combo = {}
                for line in lines:
                    color_value = self._get_or_create_attribute_value(
                        color_attr, line.variante_codigo, line.variante_nombre
                    )
                    if color_value.id not in color_value_ids:
                        color_value_ids.append(color_value.id)
                    combo = (color_value.id,)
                    if talle_attr:
                        talle_value = self._get_or_create_attribute_value(
                            talle_attr, line.presentacion_codigo, line.presentacion_nombre
                        )
                        if talle_value.id not in talle_value_ids:
                            talle_value_ids.append(talle_value.id)
                        combo = (color_value.id, talle_value.id)
                    line_by_combo[combo] = line

                self._set_attribute_line(template, color_attr, color_value_ids)
                if talle_attr:
                    self._set_attribute_line(template, talle_attr, talle_value_ids)

                self._apply_product_settings(template, first.atributos_producto)

                attrs_to_match = (color_attr, talle_attr) if talle_attr else (color_attr,)
                for variant in template.product_variant_ids:
                    combo = []
                    for attr in attrs_to_match:
                        ptav = variant.product_template_attribute_value_ids.filtered(
                            lambda p, attr=attr: p.attribute_id == attr
                        )
                        combo.append(ptav.product_attribute_value_id.id if ptav else False)
                    line = line_by_combo.get(tuple(combo))
                    if not line:
                        if (
                            talle_attr
                            and variant.active
                            and variant.id not in existing_variant_ids
                        ):
                            # Combinación NUEVA generada por el cruce Color x Talle que
                            # no existe realmente en Fenicio (ej. un color sin ese
                            # talle). Nunca se archiva una variante que ya existía antes
                            # de este sync (puede tener otra dimensión de atributo, como
                            # Color Secundario, que este código no gestiona).
                            variant.active = False
                        continue
                    variant.write({
                        'default_code': line.sku,
                        'fenicio_precio_venta': line.precio_venta,
                        'fenicio_precio_lista': line.precio_lista,
                        'fenicio_precio_alternativo': line.precio_alternativo,
                    })
                    line.odoo_product_id = variant.id
                    created += 1
            except Exception as e:
                _logger.exception('[Fenicio] Error creando producto %s', producto_codigo)
                skipped_lines |= lines
                self.env['fenicio.log'].registrar(
                    estado='error',
                    endpoint='action_create_missing',
                    request=f'Producto Fenicio {producto_codigo}: error al crear/actualizar — {e}',
                )

        self.write({
            'total_odoo': self.total_odoo + created,
            'not_found_line_ids': [(6, 0, skipped_lines.ids)],
        })
        return self._self_action()

    def action_sync_test(self):
        self.ensure_one()
        if not self.test_json or not self.test_json.strip():
            raise UserError('El JSON de prueba está vacío.')
        try:
            data = json.loads(self.test_json)
        except json.JSONDecodeError as e:
            raise UserError(f'JSON inválido: {e}')
        CatalogLine = self.env['fenicio.catalog.line']
        products = CatalogLine._extract_products(data)

        created = updated = skipped = 0
        for vals in CatalogLine._iter_lines(products):
            sku = vals.get('sku')
            if not sku:
                skipped += 1
                continue
            existing = CatalogLine.search([('sku', '=', sku)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                CatalogLine.create(vals)
                created += 1

        self.write({'total_creados': created, 'total_actualizados': updated, 'state': 'done'})
        self.env['fenicio.log'].registrar(
            estado='ok',
            endpoint='Sincronización manual (JSON)',
            request='Sincronización manual desde UI',
            mensaje=f'{created} líneas creadas, {updated} actualizadas, {skipped} sin SKU.',
        )
        return self._self_action()

    def action_open_catalog(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Catálogo Fenicio',
            'res_model': 'fenicio.catalog.line',
            'view_mode': 'tree,form',
            'target': 'current',
        }
