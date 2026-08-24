# -*- coding: utf-8 -*-

import base64
import json
import logging
from io import BytesIO

import requests
import xlsxwriter

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FenicioCatalogExport(models.TransientModel):
    _name = 'fenicio.catalog.export'
    _description = 'Exportar Catálogo Fenicio a Excel'

    excel_file = fields.Binary(string='Archivo Excel', readonly=True)
    file_name = fields.Char(default='catalogo_fenicio.xlsx')
    state = fields.Selection(
        [('draft', 'Listo'), ('done', 'Generado')],
        default='draft',
    )
    total_productos = fields.Integer(string='Productos encontrados', readonly=True)

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

    def _get_catalog_url(self):
        website = self._get_website()
        if not website:
            website = self.env['website'].search([], limit=1)
        base_url = website.fenicio_catalog_url if website else False
        if not base_url:
            raise UserError(
                'No hay una URL de catálogo configurada. '
                'Ingresá la URL base en el sitio web → pestaña Fenicio.'
            )
        return base_url.rstrip('/') + '/API_V1/catalogo'

    def _fetch_catalog(self, url):
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

    def _extract_products(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # First pass: direct list values
            for v in data.values():
                if isinstance(v, list) and v:
                    return v
            # Second pass: recurse into nested dicts (e.g. {"data": {"productos": [...]}})
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

    def _flatten(self, item):
        row = {}
        for k, v in item.items():
            row[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        return row

    def _build_excel(self, products):
        if not products:
            raise UserError('El catálogo de Fenicio no devolvió productos.')

        # Columnas: unión ordenada de todas las keys
        all_keys = []
        seen = set()
        for p in products:
            for k in p.keys():
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)

        buf = BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet('Catálogo Fenicio')

        header_fmt = wb.add_format({
            'bold': True,
            'font_color': '#FFFFFF',
            'bg_color': '#1F4E79',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        })
        cell_fmt = wb.add_format({'valign': 'top', 'text_wrap': False})

        ws.set_row(0, 30)
        ws.freeze_panes(1, 0)

        for col, key in enumerate(all_keys):
            ws.write(0, col, key, header_fmt)
            ws.set_column(col, col, max(15, min(len(str(key)) + 4, 40)))

        for row, product in enumerate(products, start=1):
            flat = self._flatten(product)
            for col, key in enumerate(all_keys):
                value = flat.get(key, '')
                if value is None:
                    value = ''
                ws.write(row, col, value, cell_fmt)

        wb.close()
        buf.seek(0)
        return buf.read()

    _SAMPLE_JSON = {
        "error": False,
        "msj": "",
        "productos": [
            {
                "cod": "4565014",
                "nom": "Gorro de lana Bariloche",
                "moneda": "UYU",
                "categ": {"id": 195, "nom": "Gorros"},
                "marca": {"id": 1, "nom": "Forum"},
                "caracts": {"genero": "Unisex"},
                "vars": [
                    {
                        "cod": "002000",
                        "nom": "Negro",
                        "desc": "",
                        "imgs": ["https://example.com/gorro-negro.jpg"],
                        "thumbs": ["https://example.com/gorro-negro-thumb.jpg"],
                        "pres": [
                            {
                                "sku": "4565014002000000",
                                "sku_fn": "1:4565014:002000:000:1",
                                "stock": 691,
                                "pr_normal": {"UYU": 499},
                                "pr_promo": {"UYU": 499},
                                "pr_lista": {"UYU": 499},
                                "identificadores": [],
                                "sku_cm": "4565014002000000",
                                "cod": "000",
                                "nom": "N/A",
                            }
                        ],
                        "caracts": {"color": "Negro"},
                    },
                    {
                        "cod": "007000",
                        "nom": "Marino",
                        "desc": "",
                        "imgs": ["https://example.com/gorro-marino.jpg"],
                        "thumbs": ["https://example.com/gorro-marino-thumb.jpg"],
                        "pres": [
                            {
                                "sku": "4565014007000000",
                                "sku_fn": "1:4565014:007000:000:1",
                                "stock": 36,
                                "pr_normal": {"UYU": 499},
                                "pr_promo": {"UYU": 499},
                                "pr_lista": {"UYU": 499},
                                "identificadores": [],
                                "sku_cm": "4565014007000000",
                                "cod": "000",
                                "nom": "N/A",
                            }
                        ],
                        "caracts": [],
                    },
                ],
            },
            {
                "cod": "4565017",
                "nom": "Cuello Polar",
                "moneda": "UYU",
                "categ": {"id": 195, "nom": "Gorros"},
                "marca": {"id": 1, "nom": "Forum"},
                "caracts": {"genero": "Unisex"},
                "vars": [
                    {
                        "cod": "002000",
                        "nom": "Negro",
                        "desc": "Cuello Polar 100% poliéster.",
                        "imgs": ["https://example.com/cuello-negro.jpg"],
                        "thumbs": ["https://example.com/cuello-negro-thumb.jpg"],
                        "pres": [
                            {
                                "sku": "4565017002000000",
                                "sku_fn": "1:4565017:002000:000:1",
                                "stock": 513,
                                "pr_normal": {"UYU": 499},
                                "pr_promo": {"UYU": 395},
                                "pr_lista": {"UYU": 499},
                                "identificadores": [],
                                "sku_cm": "4565017002000000",
                                "cod": "000",
                                "nom": "N/A",
                            }
                        ],
                        "caracts": {"color": "Negro"},
                    }
                ],
            },
        ],
    }

    def action_test(self):
        self.ensure_one()
        products = self._extract_products(self._SAMPLE_JSON)
        excel_bytes = self._build_excel(products)
        self.write({
            'excel_file': base64.b64encode(excel_bytes),
            'file_name': 'catalogo_fenicio_DEMO.xlsx',
            'state': 'done',
            'total_productos': len(products),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate(self):
        self.ensure_one()
        url = self._get_catalog_url()
        _logger.info('[Fenicio] GET %s', url)

        data = self._fetch_catalog(url)
        products = self._extract_products(data)
        excel_bytes = self._build_excel(products)

        self.write({
            'excel_file': base64.b64encode(excel_bytes),
            'file_name': 'catalogo_fenicio.xlsx',
            'state': 'done',
            'total_productos': len(products),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
