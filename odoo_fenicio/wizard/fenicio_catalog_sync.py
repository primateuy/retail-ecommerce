# -*- coding: utf-8 -*-

import json
import logging

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
            self._upsert_pricelist_item(website.fenicio_pricelist_venta_id, product, line.precio_venta)
            self._upsert_pricelist_item(website.fenicio_pricelist_lista_id, product, line.precio_lista)
            self._upsert_pricelist_item(website.fenicio_pricelist_alternativo_id, product, line.precio_alternativo)
            line.odoo_product_id = product.id
            updated += 1

        self.write({'total_odoo': updated, 'not_found_line_ids': [(6, 0, not_found.ids)], 'state': 'done'})
        return self._self_action()

    def action_create_missing(self):
        self.ensure_one()
        created = 0
        for line in self.not_found_line_ids:
            tmpl = self.env['product.template'].create({
                'name': line.producto_nombre or line.variante_nombre or line.sku,
                'product_e_fenicio': True,
                'type': 'consu',
                'list_price': line.precio_venta,
            })
            variant = tmpl.product_variant_ids[:1]
            if variant:
                variant.default_code = line.sku
                line.odoo_product_id = variant.id
            created += 1

        self.write({'total_odoo': self.total_odoo + created, 'not_found_line_ids': [(5, 0, 0)]})
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
