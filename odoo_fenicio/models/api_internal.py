# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ApiInternal(models.Model):
    _name = 'api.internal'
    _description = 'API Interna'

    @api.model
    def change_date(self, date_str):
        if date_str and 'T' in date_str:
            return date_str[0:10]
        return date_str

    @api.model
    def verificar_token(self, token):
        store_token = self.env['ir.config_parameter'].sudo().get_param('token_autenticacion_efenicio')
        if store_token != token:
            raise UserError('El token de autenticacion efenicio es incorrecto.')
        return True

    @api.model
    def listar_productos(self, json_data):
        product_template_ids = self.env['product.template'].search([
            ('product_e_fenicio', '=', True),
            ('fenicio_check', '=', False),
        ], limit=json_data['total'], offset=json_data['desde'], order='id asc')
        response = {'desde': json_data['desde'], 'total': len(product_template_ids), 'productos': []}

        for product_template_id in product_template_ids:
            vals = {
                'codigo': product_template_id.code_e_fenicio or '',
                'nombre': product_template_id.name,
                'fechaCreacion': product_template_id.create_date.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                'prioridad': product_template_id.priority_fenicio,
                'guiaTalles': product_template_id.guia_talles,
                'monedaPredeterminada': product_template_id.default_currency_id.display_name,
                'impuesto': (len(product_template_id.taxes_id) > 0 and product_template_id.taxes_id[0].amount) or 0.0,
                'atributos': {
                    'categoria': product_template_id.categ_id.display_name.replace(' ', '').replace(' ', ''),
                    'marca': product_template_id.brand,
                },
                'variantes': [],
            }

            for product_setting_id in product_template_id.product_settings_ids:
                vals['atributos'][product_setting_id.attribute_id.name] = product_setting_id.value_id.name

            # Configuraciones de variantes dentro de product.template de tipo "Presentación"
            configuraciones_variantes_tipo_presentacion_ids = product_template_id.attribute_line_ids.filtered(lambda l: l.attribute_id.fenicio_type == 'presentacion')

            # Configuraciones de variantes dentro de product.template de tipo "Variante"
            configuraciones_variantes_tipo_variante_ids = product_template_id.attribute_line_ids.filtered(lambda l: l.attribute_id.fenicio_type == 'variante')

            for attribute_line_id in configuraciones_variantes_tipo_variante_ids:
                for attribute_value_id in attribute_line_id.value_ids:

                    def filter_product_product(product_product_filter_id):
                        return (attribute_line_id, attribute_value_id) in product_product_filter_id.product_template_attribute_value_ids.mapped(lambda l: (l.attribute_line_id, l.product_attribute_value_id))

                    product_product_ids = product_template_id.product_variant_ids.filtered(filter_product_product)

                    if len(product_product_ids) > 0:

                        codigo_variante = attribute_value_id.fenicio_attribute_value_code
                        if len(attribute_line_id.value_ids) == 1:
                            codigo_variante = product_template_id.code_e_fenicio or ''

                        variante = {
                            'codigo': codigo_variante,
                            'nombre': attribute_value_id.name,
                            'atributos': {},
                        }

                        presentaciones = []
                        for attribute_line_presentacion_id in configuraciones_variantes_tipo_presentacion_ids:
                            for attribute_value_presentacion_id in attribute_line_presentacion_id.value_ids:

                                def filter_product_product(product_product_filter_id):
                                    return (attribute_line_presentacion_id, attribute_value_presentacion_id) in product_product_filter_id.product_template_attribute_value_ids.mapped(lambda l: (l.attribute_line_id, l.product_attribute_value_id))

                                product_product_presentacion_ids = product_product_ids.filtered(filter_product_product)

                                for product_product_presentacion_id in product_product_presentacion_ids:
                                    stock_quant_id = self.env['stock.quant'].search([
                                        ('product_id', '=', product_product_presentacion_id.id),
                                        ('on_hand', '=', True),
                                    ], limit=1)

                                    # PRECIOS ALTERNATIVOS
                                    precios_aleternativos = []
                                    precios_aleternativos_ids = product_product_presentacion_id.precios_alternativos_fenicio_ids
                                    for precio_alternativo_id in precios_aleternativos_ids:
                                        alternative_sales_prices_ids = precio_alternativo_id.precios_lista_venta_ids.filtered(lambda l: l.price_type == 'precioVenta')
                                        alternative_sales_prices_vals = {}
                                        for sale_price_id in alternative_sales_prices_ids:
                                            alternative_sales_prices_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                                        alternative_sales_prices_ids = precio_alternativo_id.precios_lista_venta_ids.filtered(lambda l: l.price_type == 'precioLista')
                                        alternative_sales_prices_list_vals = {}
                                        for sale_price_id in alternative_sales_prices_ids:
                                            alternative_sales_prices_list_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                                        precio_aleternativo = {
                                            'codigo': precio_alternativo_id.code,
                                            'precioLista': alternative_sales_prices_list_vals,
                                            'precioVenta': alternative_sales_prices_vals,
                                        }
                                        precios_aleternativos.append(precio_aleternativo)

                                    product_template_currency_id = product_template_id.default_currency_id

                                    # PRECIO VENTA PRESENTACION
                                    sales_prices_ids = product_product_presentacion_id.precios_fenicio_ids.filtered(lambda l: l.price_type == 'precioVenta')
                                    sales_prices_vals = {}
                                    for sale_price_id in sales_prices_ids:
                                        sales_prices_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                                    # PRECIO Lista PRESENTACION
                                    sales_prices_ids = product_product_presentacion_id.precios_fenicio_ids.filtered(lambda l: l.price_type == 'precioLista')
                                    sales_prices_list_vals = {}
                                    for sale_price_id in sales_prices_ids:
                                        sales_prices_list_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                                    # IDENTIFICADORES
                                    identificadores_ids = product_product_presentacion_id.indentificadores_ids
                                    identificadores_list = []
                                    for identificador_id in identificadores_ids:
                                        identificadores_list.append({
                                            'codigo': identificador_id.code,
                                            'value': identificador_id.value,
                                        })

                                    codigo_presentacion = product_product_presentacion_id.default_code or ''
                                    if len(attribute_line_presentacion_id.value_ids) == 1:
                                        codigo_presentacion = 'U'

                                    presentaciones.append({
                                        'codigo': codigo_presentacion,
                                        'nombre': attribute_value_presentacion_id.name,
                                        'sku': product_product_presentacion_id.default_code or '',
                                        'stock': (stock_quant_id and stock_quant_id.quantity) or 0.0,
                                        "precioLista": sales_prices_list_vals,
                                        "precioVenta": sales_prices_vals,
                                        "preciosAlternativos": precios_aleternativos,
                                        "identificadores": identificadores_list,
                                    })

                        variante['presentaciones'] = presentaciones

                        for variante_id in product_product_ids:
                            for variante_name_value_id in variante_id.product_template_attribute_value_ids.filtered(lambda l: not l.attribute_id.fenicio_type):
                                variante['atributos'][variante_name_value_id.attribute_id.display_name] = variante_name_value_id.product_attribute_value_id.name

                        vals['variantes'].append(variante)

            if len(vals['variantes']) == 0 and len(product_template_id.product_variant_ids) == 1:
                for variante_id in product_template_id.product_variant_ids:
                    stock_quant_id = self.env['stock.quant'].search([
                        ('product_id', '=', variante_id.id),
                        ('on_hand', '=', True),
                    ])

                    # PRECIOS ALTERNATIVOS
                    precios_aleternativos = []
                    precios_aleternativos_ids = variante_id.precios_alternativos_fenicio_ids
                    for precio_alternativo_id in precios_aleternativos_ids:
                        alternative_sales_prices_ids = precio_alternativo_id.precios_lista_venta_ids.filtered(lambda l: l.price_type == 'precioVenta')
                        alternative_sales_prices_vals = {}
                        for sale_price_id in alternative_sales_prices_ids:
                            alternative_sales_prices_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                        alternative_sales_prices_ids = precio_alternativo_id.precios_lista_venta_ids.filtered(lambda l: l.price_type == 'precioLista')
                        alternative_sales_prices_list_vals = {}
                        for sale_price_id in alternative_sales_prices_ids:
                            alternative_sales_prices_list_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                        precio_aleternativo = {
                            'codigo': precio_alternativo_id.code,
                            'precioLista': alternative_sales_prices_list_vals,
                            'precioVenta': alternative_sales_prices_vals,
                        }
                        precios_aleternativos.append(precio_aleternativo)

                    # PRECIO VENTA PRESENTACION
                    sales_prices_ids = variante_id.precios_fenicio_ids.filtered(lambda l: l.price_type == 'precioVenta')
                    sales_prices_vals = {}
                    for sale_price_id in sales_prices_ids:
                        sales_prices_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                    # PRECIO Lista PRESENTACION
                    sales_prices_ids = variante_id.precios_fenicio_ids.filtered(lambda l: l.price_type == 'precioLista')
                    sales_prices_list_vals = {}
                    for sale_price_id in sales_prices_ids:
                        sales_prices_list_vals[sale_price_id.currency_id.display_name] = sale_price_id.price

                    # IDENTIFICADORES
                    identificadores_ids = variante_id.indentificadores_ids
                    identificadores_list = []
                    for identificador_id in identificadores_ids:
                        identificadores_list.append({
                            'codigo': identificador_id.code,
                            'value': identificador_id.value,
                        })

                    variante = {
                        'codigo': variante_id.default_code or '',
                        'nombre': variante_id.name,
                        'atributos': {},
                        'presentaciones': [{
                            'codigo': 'U',
                            'nombre': variante_id.name,
                            'sku': variante_id.default_code or '',
                            'stock': (stock_quant_id and stock_quant_id.quantity) or 0.0,
                            "precioLista": sales_prices_list_vals,
                            "precioVenta": sales_prices_vals,
                            "preciosAlternativos": precios_aleternativos,
                            "identificador": identificadores_list,
                        }]
                    }

                    for variante_name_value_id in variante_id.product_template_attribute_value_ids:
                        variante['atributos'][variante_name_value_id.attribute_id.display_name] = variante_name_value_id.product_attribute_value_id.name

                    vals['variantes'].append(variante)

            response['productos'].append(vals)

        return response

    @api.model
    def stock_producto(self, json_data):
        skus_pedido = json_data['skus']

        product_ids = self.env['product.product'].search([('default_code', 'in', skus_pedido)])

        skus_encontrados = set(product_ids.mapped('default_code'))
        sku_no_encontrados = set(skus_pedido) - set(skus_encontrados)

        vals_list = []

        stock_quant_encontrados_ids = self.env['stock.quant']

        for product_id in product_ids:
            stock_quant_id = self.env['stock.quant'].search([
                ('product_id', '=', product_id.id),
                ('on_hand', '=', True),
            ], limit=1)

            if stock_quant_id:
                stock_quant_encontrados_ids += stock_quant_id
                vals = {
                    "sku": stock_quant_id.product_id.default_code,
                    "stock": stock_quant_id.quantity,
                }
                vals_list.append(vals)

        sku_sin_stock = product_ids - stock_quant_encontrados_ids.mapped('product_id')
        for product_id in sku_sin_stock:
            vals = {
                "sku": product_id.default_code,
                "stock": 0.0,
            }
            vals_list.append(vals)

        response = {
            'stockPorSku': vals_list,
        }

        msg = ''
        if len(sku_no_encontrados) > 0:
            msg = f'Los siguientes sku no fueron encontrados: {sku_no_encontrados}'

        return response, msg

    @api.model
    def crear_orden_venta(self, json_data):
        estados = ['EN_CURSO', 'APROBADA', 'ABANDONADA', 'PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'CANCELADA']

        # verificar que sea un estado valido
        if 'estado' not in json_data or json_data['estado'] not in estados:
            return {'error': 'Estado de la orden no válido'}

        # obtener el valor del estado
        estado = json_data['estado']
        # obtener el id de la orden
        id_orden_fenicio = json_data['idOrden']

        SALE_ORDER_ENV = self.env['sale.order']
        # obtener cualquier orden anteriormente creada
        sale_order_id = SALE_ORDER_ENV.search([('id_order_fenicio', '=', id_orden_fenicio)], limit=1)

        # boolean para saber si la orden es recien creada o no
        is_new_order = False

        error = ''
        if sale_order_id and sale_order_id.state == 'draft' and estado == 'EN_CURSO':
            # si hay un presupuesto y el estado del json es EN_CURSO:
            # actualizar los datos de la orden
            sale_order_id, error = sale_order_id.create_or_update_order(json_data)
        elif not sale_order_id:
            # si no existe ninguna orden: crearla
            sale_order_id, error = SALE_ORDER_ENV.create_or_update_order(json_data)
            is_new_order = True

        # si no se pudo crear la orden: retornar error
        if not sale_order_id:
            return {'error': error}

        if estado in ['PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'APROBADA']:
            if sale_order_id.state in ['draft', 'sent']:
                sale_order_id.action_confirm()

            # si no es recien creada la orden: actualizar los datos de fenicio
            if not is_new_order:
                sale_order_id.update_fenicio(json_data)

        cancelable = False
        if estado in ['ABANDONADA', 'CANCELADA']:
            # cancelable, cancel_error = SALE_ORDER_ENV.is_cancelable(id_orden_fenicio)
            cancelable = True

        _logger.info("La orden {} {}será cancelada.".format(id_orden_fenicio, "" if cancelable else "no "))

        if cancelable:
            invoices_ids = sale_order_id.invoice_ids
            picking_ids = sale_order_id.picking_ids

            # payment_ids = self.env['account.payment'].search([('invoice_ids', 'in', invoices_ids.ids)])
            ids_payment = []
            for invoice_id in invoices_ids:
                reconciled_invoices_partials = invoice_id._get_reconciled_invoices_partials()
                ids_payment += list(map(lambda l: l[2].payment_id and l[2].payment_id.id or False, reconciled_invoices_partials))

            payment_ids = self.env['account.payment'].search([('id', 'in', ids_payment)])
            payment_ids.action_draft()
            payment_ids.action_cancel()

            # No se puede por FACTURACION ELECTRONICA TOCA HACER NOTA DE CREDITO
            # invoices_ids.button_draft()
            # invoices_ids.button_cancel()
            invoices_ids.crear_nota_credito()

            # picking_ids.action_cancel()
            for picking_id in picking_ids:
                move_lines_ids = picking_id.mapped('move_lines')
                any_done = any(move.state == 'done' for move in move_lines_ids)

                if not any_done:
                    picking_ids.action_cancel()
                else:
                    w_id = self.env['stock.return.picking'].create({
                        'picking_id': picking_id.id,
                    })
                    w_id._onchange_picking_id()
                    new_picking_id, pick_type_id = w_id._create_returns()
                    new_picking_id = self.env['stock.picking'].search([('id', '=', new_picking_id)], limit=1)
                    if new_picking_id:
                        new_picking_id.auto_validate()

            sale_order_id.action_cancel()

        if 'picking' in json_data and json_data['picking'] == 0:
            return {'referencia': sale_order_id.display_name}

        picking_error = False
        if 'entrega' in json_data and not cancelable:
            picking_error = sale_order_id.actualizar_pickings(json_data)

        if picking_error:
            return {'error': picking_error}

        if estado in ['PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'APROBADA']:
            if len(sale_order_id.invoice_ids) == 0:
                sale_order_id.create_invoice_fenicio()
                invoice_ids = sale_order_id.invoice_ids
                plazo_pago_id = self.env['account.payment.term'].search([('for_fenicio', '=', True)], limit=1)
                if plazo_pago_id:
                    invoice_ids.write({
                        'invoice_payment_term_id': plazo_pago_id and plazo_pago_id.id,
                    })
                invoice_ids.action_post()

            if estado == 'APROBADA' and 'pago' in json_data and json_data['pago'] and json_data['pago']['estado'] not in ['PENDIENTE', 'ERROR', 'REVERSADO']:
                json_data_pago = json_data['pago']
                invoice_ids = sale_order_id.invoice_ids
                for invoice_id in invoice_ids:
                    # reconciled_invoices_partials = invoice_id._get_reconciled_invoices_partials()
                    payment_ids = invoice_id.payment_ids

                    # ids_payment = list(map(lambda l: l[2].payment_id and l[2].payment_id.id or False, reconciled_invoices_partials))
                    # payment_ids = self.env['account.payment'].search([('id', 'in', ids_payment)])
                    payment_id = invoice_id.create_payment_fenicio(json_data_pago, mode_update=(len(payment_ids) > 0), payment_ids=payment_ids)

        return {'referencia': sale_order_id.display_name}

    @api.model
    def puede_cancelar(self, json_data):
        SALE_ORDER_ENV = self.env['sale.order']
        cancelable, error = SALE_ORDER_ENV.is_cancelable(json_data['idOrden'])

        return {
            'permiteCancelar': cancelable,
            'motivoRechazo': error
        }
