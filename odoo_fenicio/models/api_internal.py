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
        _logger.info("ENTRANDO ACA => %s", json_data)
        
        # Obtener parámetros con valores por defecto
        limit = json_data.get('total', 100)
        offset = json_data.get('desde', 0)
        
        product_template_ids = self.env['product.template'].search([
            ('product_e_fenicio', '=', True),
            ('fenicio_check', '=', False),
        ], limit=limit, offset=offset, order='id asc')

        response = {
            'desde': offset, 
            'total': len(product_template_ids), 
            'productos': []
        }

        for product_template_id in product_template_ids:
            listaCategoria = ''
            
            if product_template_id.product_variant_ids:
                first_variant = product_template_id.product_variant_ids[0]
                
                if hasattr(first_variant, 'public_categ_ids') and first_variant.public_categ_ids:
                    categorias = [cat.fenicio_code for cat in first_variant.public_categ_ids]
                    listaCategoria = '\/'.join(categorias)
                
            

            impuesto = product_template_id.taxes_id and product_template_id.taxes_id[0].amount or 'Sin Impuesto'

            vals = {
                'codigo': str(product_template_id.code_e_fenicio or product_template_id.id),
                'nombre': product_template_id.name,
                'fechaCreacion': product_template_id.create_date.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'prioridad': product_template_id.priority_fenicio or 1,
                'guiaTalles': product_template_id.guia_talle_code or '',
                'monedaPredeterminada': self.env.company.currency_id.name,
                'impuesto': impuesto,
                'atributos': {
                    'categoria': listaCategoria,
                    'marca': product_template_id.product_brand_id.fenicio_brand_id if product_template_id.product_brand_id and product_template_id.product_brand_id.fenicio_brand_id else '0',
                    'descripcion': product_template_id.descripcion_fenicio or '',
                },
                'variantes': [],
            }

            

            if len(product_template_id.product_variant_ids) > 1:
                for variante in product_template_id.product_variant_ids:
                    variant_attrs = variante.product_template_attribute_value_ids.filtered(
                        lambda x: x.attribute_id.fenicio_type == 'variante'
                    ).sorted(lambda x: x.attribute_id.sequence)

                    presentacion_attrs = variante.product_template_attribute_value_ids.filtered(
                        lambda x: x.attribute_id.fenicio_type == 'presentacion'
                    ).sorted(lambda x: x.attribute_id.sequence)

                    
                    codigo_parts = []
                    nombre_parts = []
                    atributos = {}
                    


                    for attr_val in variant_attrs:
                        _logger.info(f"Processing variant attribute: {attr_val}");

                        codigo_parts.append(str(attr_val.attribute_id.codigo) if attr_val.attribute_id.codigo else '000');
                        
                        nombre_parts.append(attr_val.product_attribute_value_id.name)
                        
                        # Atributos
                        atributos[attr_val.attribute_id.name] = attr_val.product_attribute_value_id.name
                    
                    codigo_variante = ''.join(codigo_parts)
                    nombre_variante = ' / '.join(nombre_parts)
            


                    variante_data = {
                        'codigo': codigo_variante,
                        'nombre': nombre_variante,
                        'atributos': atributos,
                        'presentaciones': [],
                    }

                    listaVenta = variante.pricelist_relation_ids.precio_venta;
                    listaPrecios = variante.pricelist_relation_ids.precio_lista;
                    listaAlternativo = variante.pricelist_relation_ids.precio_alternativo;
                    

                    for pres_attr_val in presentacion_attrs:
                        codigo = str(pres_attr_val.attribute_id.codigo) if pres_attr_val.attribute_id.codigo else '000'
                        nombre = pres_attr_val.product_attribute_value_id.name
                        sku = variante.default_code or '';
                        stock = self._get_fenicio_stock(variante);

                        precioVenta = 0.0;
                        precioLista = 0.0;
                        precioAlternativo = 0.0;

                        for item in listaVenta:
                            for precio in item.item_ids:
                                if precio.product_id.id == variante.id:
                                    precioVenta = precio.fixed_price;

                        for item in listaPrecios:
                            for precio in item.item_ids:
                                if precio.product_id.id == variante.id:
                                    precioLista = precio.fixed_price;

                        for item in listaAlternativo:
                            for precio in item.item_ids:
                                if precio.product_id.id == variante.id:
                                    precioAlternativo = precio.fixed_price;
                    
                        variante_data['presentaciones'].append(
                            {
                                'codigo': codigo,
                                'nombre': nombre,
                                'stock': stock,
                                'sku': sku,
                                'precioLista': {'precio': precioLista},
                                'precioVenta': {
                                    'precio': precioVenta
                                },
                                'precioAlternativo': {
                                    'precio': precioAlternativo
                                }
                            }
                        )



                    vals['variantes'].append(variante_data)


                    
                        
            elif len(product_template_id.product_variant_ids) == 1:
                product_id = product_template_id.product_variant_ids[0]
                
                variante = {
                    'codigo': str(product_id.default_code or product_template_id.id),
                    'nombre': product_id.name,
                    'atributos': {},
                    'presentaciones': []
                }

                # Agregar presentación única
                presentacion_data = self._build_presentacion_data(product_id, product_id.name, True, codigo_unico=True)
                variante['presentaciones'].append(presentacion_data)

                # Agregar atributos del producto
                for attr_val in product_id.product_template_attribute_value_ids:
                    variante['atributos'][attr_val.attribute_id.display_name] = attr_val.product_attribute_value_id.name

                vals['variantes'].append(variante)

            response['productos'].append(vals)

        return response


    def _get_fenicio_stock(self, product_id):
    # Obtener ubicaciones visibles para Fenicio
        fenicio_locations = self.env['stock.location'].search([
            ('fenicio_visible', '=', True),
            ('usage', '=', 'internal')
        ])
        
        if not fenicio_locations:
            _logger.warning("Producto %s: No hay ubicaciones Fenicio configuradas", product_id.default_code)
            return 0.0
        
        _logger.info("Ubicaciones Fenicio encontradas: %s", fenicio_locations.mapped('name'))
        
        # Obtener el tope máximo de stock a mostrar
        variante = self.env['product.product'].browse(product_id.id);
        
        tope_maximo = variante.available_threshold if variante.show_availability and variante.available_threshold > 0 else 25;

        
        stock_atp = 0.0
        for location in fenicio_locations:
            qty_atp = self.env['stock.quant']._get_available_quantity(product_id, location)
            _logger.info("  - %s: %.2f unidades (ATP)", location.name, qty_atp)
            stock_atp += qty_atp
        
        
        
        stock_final = min(stock_atp, tope_maximo)
        
        return stock_final


    @api.model
    def _build_variant_name(self, product_product_ids):
        """Construir nombre: Color + " / " + Color Secundario"""
        if not product_product_ids:
            return ""
            
        product_id = product_product_ids[0]
        
        
        color_attr = product_id.product_template_attribute_value_ids.filtered(
            lambda l: l.attribute_id.fenicio_code == 'color'
        )
        
        color_sec_attr = product_id.product_template_attribute_value_ids.filtered(
            lambda l: l.attribute_id.fenicio_code == 'color_secundario' 
        )
        
        color_name = color_attr.product_attribute_value_id.name if color_attr else ""
        color_sec_name = color_sec_attr.product_attribute_value_id.name if color_sec_attr else ""
        
        if color_name and color_sec_name:
            return f"{color_name} / {color_sec_name}"
        elif color_name:
            return color_name
        else:
            return product_id.name

    @api.model
    def _build_presentacion_data(self, product_id, nombre_presentacion, es_unico=False, codigo_unico=False):
        """Construir datos de presentación para un producto"""
        
        # Obtener stock
        stock_quant_id = self.env['stock.quant'].search([
            ('product_id', '=', product_id.id),
            ('on_hand', '=', True),
        ], limit=1)
        
        stock = stock_quant_id.quantity if stock_quant_id else 0.0

        # Obtener precios de lista
        precios_lista_ids = product_id.precios_fenicio_ids.filtered(lambda l: l.price_type == 'precioLista')
        precio_lista = {}
        for precio in precios_lista_ids:
            precio_lista[precio.currency_id.name] = precio.price

        # Obtener precios de venta
        precios_venta_ids = product_id.precios_fenicio_ids.filtered(lambda l: l.price_type == 'precioVenta')
        precio_venta = {}
        for precio in precios_venta_ids:
            precio_venta[precio.currency_id.name] = precio.price

        # Obtener precios alternativos
        precios_alternativos = []
        for precio_alt in product_id.precios_alternativos_fenicio_ids:
            alt_lista_ids = precio_alt.precios_lista_venta_ids.filtered(lambda l: l.price_type == 'precioLista')
            alt_venta_ids = precio_alt.precios_lista_venta_ids.filtered(lambda l: l.price_type == 'precioVenta')
            
            alt_precio_lista = {}
            for precio in alt_lista_ids:
                alt_precio_lista[precio.currency_id.name] = precio.price
                
            alt_precio_venta = {}
            for precio in alt_venta_ids:
                alt_precio_venta[precio.currency_id.name] = precio.price

            precios_alternativos.append({
                'codigo': precio_alt.code,
                'precioLista': alt_precio_lista,
                'precioVenta': alt_precio_venta,
            })

        # Obtener identificadores
        identificadores = []
        for identificador in product_id.indentificadores_ids:
            identificadores.append({
                'codigo': identificador.code,
                'valor': identificador.value,  # Corregido de 'value' a 'valor'
            })

        # Determinar código de presentación
        if codigo_unico:
            codigo = 'U'
        elif es_unico:
            codigo = 'U'
        else:
            codigo = product_id.default_code or str(product_id.id)

        return {
            'codigo': codigo,
            'nombre': nombre_presentacion,
            'sku': product_id.default_code or '',
            'stock': stock,
            'precioLista': precio_lista,
            'precioVenta': precio_venta,
            'preciosAlternativos': precios_alternativos,
            'identificadores': identificadores,  # Corregido de 'identificador' a 'identificadores'
        }

    @api.model
    def stockporsku(self, json_data):
        skus_pedido = json_data['skus']

        productos = [];

        for sku in skus_pedido:
            product_id = self.env['product.product'].search([('default_code', '=', sku)], limit=1)
            if product_id:
                productos.append(product_id)

        

        _logger.info(f"PRODUCTOS ENCONTRADOS => {len(productos)}")
        
        skus_encontrados = set(productos.mapped('default_code'))
        sku_no_encontrados = set(skus_pedido) - set(skus_encontrados)

        vals_list = []



        stock_quant_encontrados_ids = self.env['stock.quant']

        for product_id in productos:
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

        sku_sin_stock = productos - stock_quant_encontrados_ids.mapped('product_id')
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

        _logger.info("ANTES DE PAGAR");
        if 'picking' in json_data and json_data['picking'] == 0:
            return {'referencia': sale_order_id.display_name}

        # IMPORTANTE: Actualizar pickings ANTES de crear facturas
        # para que los productos estén marcados como entregados
        _logger.info("ANTES DE PICKING");
        picking_error = False
        if 'entrega' in json_data and not cancelable:
            picking_error = sale_order_id.actualizar_pickings(json_data)

        _logger.info("SALIENDO DE PICKING");
        if picking_error:
            return {'error': picking_error}

        _logger.info("ANTES DE PAGO");
        if estado in ['PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'APROBADA']:
            _logger.info("ANTES DE CREAR FACTURA");
            if len(sale_order_id.invoice_ids) == 0:
                sale_order_id.create_invoice_fenicio()
                invoice_ids = sale_order_id.invoice_ids
                plazo_pago_id = self.env['account.payment.term'].search([('for_fenicio', '=', True)], limit=1)
                if plazo_pago_id:
                    invoice_ids.write({
                        'invoice_payment_term_id': plazo_pago_id and plazo_pago_id.id,
                    })
                invoice_ids.action_post()

            _logger.info("ANTES DE PAGO");
            if estado == 'APROBADA' and 'pago' in json_data and json_data['pago'] and json_data['pago']['estado'] not in ['PENDIENTE', 'ERROR', 'REVERSADO']:
                json_data_pago = json_data['pago']
                invoice_ids = sale_order_id.invoice_ids
                for invoice_id in invoice_ids:
                    # reconciled_invoices_partials = invoice_id._get_reconciled_invoices_partials()
                    payment_ids = invoice_id.payment_ids

                    # ids_payment = list(map(lambda l: l[2].payment_id and l[2].payment_id.id or False, reconciled_invoices_partials))
                    # payment_ids = self.env['account.payment'].search([('id', 'in', ids_payment)])
                    payment_id = invoice_id.create_payment_fenicio(json_data_pago, mode_update=(len(payment_ids) > 0), payment_ids=payment_ids)

        _logger.info("SALIENDO DE PAGAR");
        return {'referencia': sale_order_id.display_name}

    @api.model
    def puede_cancelar(self, json_data):
        SALE_ORDER_ENV = self.env['sale.order']
        cancelable, error = SALE_ORDER_ENV.is_cancelable(json_data['idOrden'])

        return {
            'permiteCancelar': cancelable,
            'motivoRechazo': error
        }
