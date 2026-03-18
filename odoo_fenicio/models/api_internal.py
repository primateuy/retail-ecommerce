# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

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
        if not token:
            raise UserError('No se proporcionó un token de autenticación.')
        company = self.env['res.company'].sudo().search([('fenicio_token', '=', token)], limit=1)

        _logger.info("La compañia que tiene el token es: %s", company.name)
        if not company:
            raise UserError('El token de autenticación efenicio es incorrecto o no está asociado a ninguna compañía.')
        return company

    

    @api.model
    def listar_productos(self, json_data, token):
        
        limit = json_data.get('total', 100)
        offset = json_data.get('desde', 0)
        empresa = self.verificar_token(token)
        currency_code = empresa.currency_id.name
        
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
                    
                    listaCategoria = first_variant.public_categ_ids[0].fenicio_code or '000';

                
            

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

            for atributos in product_template_id.product_settings_ids:
                codigo_atributo = atributos.attribute_id.codigo if atributos.attribute_id.codigo else '000'

                codigo_variante = atributos.value_id.fenicio_attribute_value_code if atributos.value_id.fenicio_attribute_value_code else '000'

                vals['atributos'][codigo_atributo] = codigo_variante;


            

            if len(product_template_id.product_variant_ids) > 1:
                # Agrupar variantes por atributos de variante
                variantes_map = {}
                
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
                        codigo_fenicio = attr_val.product_attribute_value_id.fenicio_attribute_value_code
                        
                        # Todos los valores posibles del atributo en el template
                        todos_los_valores = [
                            v.name 
                            for v in attr_val.attribute_id.value_ids
                            if v.id in product_template_id.attribute_line_ids.filtered(
                                lambda l: l.attribute_id.id == attr_val.attribute_id.id
                            ).value_ids.ids
                        ]

                        codigo_parts.append(str(codigo_fenicio) if codigo_fenicio else '000')
                        nombre_parts.append(', '.join(todos_los_valores))  # ← todos los valores

                        clave = attr_val.attribute_id.name
                        atributos[clave] = ', '.join(todos_los_valores) if len(todos_los_valores) > 1 else todos_los_valores[0]

                    nombre_variante = ' / '.join(nombre_parts)
                    codigo_variante = ''.join(codigo_parts)

            

                    # Usar código de variante como clave para agrupar
                    if codigo_variante not in variantes_map:
                        variantes_map[codigo_variante] = {
                            'codigo': codigo_variante,
                            'nombre': nombre_variante,
                            'atributos': atributos,
                            'presentaciones': [],
                        }

                    listaVenta = self.env.company.fenicio_pricelist_venta_id
                    listaPrecios = self.env.company.fenicio_pricelist_lista_id
                    listaAlternativo = self.env.company.fenicio_pricelist_alternativo_id
                    

                    if not presentacion_attrs:
                        codigo = variante.default_code or ''
                        nombre = variante.name
                        sku = variante.default_code or ''
                        stock = self._get_fenicio_stock(variante, token)

                        precioVenta = 0.0
                        precioLista = 0.0
                        precioAlternativo = 0.0

                        if listaVenta:
                            try:
                                precioVenta = listaVenta._get_product_price(
                                    product=variante,
                                    quantity=1.0,
                                    partner=None,
                                    uom_id=variante.uom_id.id
                                )
                            except Exception as e:
                                precioVenta = variante.lst_price or 0.0

                        if listaPrecios:
                            try:
                                precioLista = listaPrecios._get_product_price(
                                    product=variante,
                                    quantity=1.0,
                                    partner=None,
                                    uom_id=variante.uom_id.id
                                )
                            except Exception as e:
                                precioLista = variante.lst_price or 0.0

                        if listaAlternativo:
                            try:
                                precioAlternativo = listaAlternativo._get_product_price(
                                    product=variante,
                                    quantity=1.0,
                                    partner=None,
                                    uom_id=variante.uom_id.id
                                )
                            except Exception as e:
                                precioAlternativo = variante.lst_price or 0.0

                        variantes_map[codigo_variante]['presentaciones'].append(
                            {
                                'codigo': codigo,
                                'nombre': nombre,
                                'stock': stock,
                                'sku': sku,
                                'precioLista': {currency_code: precioLista},
                                'precioVenta': {currency_code: precioVenta},
                                'precioAlternativo': {currency_code: precioAlternativo}
                            }
                        )
                    else:
                        for pres_attr_val in presentacion_attrs:
                            codigo = pres_attr_val.product_attribute_value_id.fenicio_attribute_value_code if pres_attr_val.product_attribute_value_id.fenicio_attribute_value_code else '000'
                            nombre = pres_attr_val.product_attribute_value_id.name
                            sku = variante.default_code or ''
                            stock = self._get_fenicio_stock(variante, token)

                            precioVenta = 0.0
                            precioLista = 0.0
                            precioAlternativo = 0.0

                            if listaVenta:
                                try:
                                    precioVenta = listaVenta._get_product_price(
                                        product=variante,
                                        quantity=1.0,
                                        partner=None,
                                        uom_id=variante.uom_id.id
                                    )

                                except Exception as e:
                                    precioVenta = variante.lst_price or 0.0

                            if listaPrecios:
                                try:
                                    precioLista = listaPrecios._get_product_price(
                                        product=variante,
                                        quantity=1.0,
                                        partner=None,
                                        uom_id=variante.uom_id.id
                                    )

                                except Exception as e:
                                    precioLista = variante.lst_price or 0.0

                            if listaAlternativo:
                                try:
                                    precioAlternativo = listaAlternativo._get_product_price(
                                        product=variante,
                                        quantity=1.0,
                                        partner=None,
                                        uom_id=variante.uom_id.id
                                    )
                                except Exception as e:
                                    precioAlternativo = variante.lst_price or 0.0

                            variantes_map[codigo_variante]['presentaciones'].append(
                                {
                                    'codigo': codigo,
                                    'nombre': nombre,
                                    'stock': stock,
                                    'sku': sku,
                                    'precioLista': {currency_code: precioLista},
                                    'precioVenta': {currency_code: precioVenta},
                                    'precioAlternativo': {currency_code: precioAlternativo}
                                }
                            )

                for variante_data in variantes_map.values():
                    vals['variantes'].append(variante_data)


                    
                        
            elif len(product_template_id.product_variant_ids) == 1:
                product_id = product_template_id.product_variant_ids[0]
                
                variante = {
                    'codigo': str(product_id.default_code or product_template_id.id),
                    'nombre': product_id.name,
                    'atributos': {},
                    'presentaciones': []
                }

                presentacion_data = self._build_presentacion_data(product_id, product_id.name, True, codigo_unico=True, token=token)
                variante['presentaciones'].append(presentacion_data)

                for attr_val in product_id.product_template_attribute_value_ids:
                    variante['atributos'][attr_val.attribute_id.display_name] = attr_val.product_attribute_value_id.name

                vals['variantes'].append(variante)

            response['productos'].append(vals)

        return response


    def _get_fenicio_stock(self, product_id, token):
    # Obtener ubicaciones configuradas para la compañía
        fenicio_locations = self.env.company.fenicio_stock_location_ids
        
        if not fenicio_locations:
            _logger.warning("Producto %s: No hay ubicaciones Fenicio configuradas para la compañía %s", product_id.default_code, self.env.company.id)
            return 0.0
        
        
        # Obtener el tope máximo de stock a mostrar
        variante = self.env['product.product'].browse(product_id.id);
        
        empresa = self.verificar_token(token);

        if not empresa or not empresa.cantidad_stock_bydefault:
            cantidad_bydefault = 0
        else:
            cantidad_bydefault = empresa.cantidad_stock_bydefault

        tope_maximo = variante.available_threshold if variante.show_availability and variante.available_threshold > 0 else cantidad_bydefault



        
        stock_atp = 0.0
        for location in fenicio_locations:
            qty_atp = self.env['stock.quant']._get_available_quantity(product_id, location)
            stock_atp += qty_atp
        
        _logger.info(f"Stock por defecto {cantidad_bydefault}, stock ATP {stock_atp}, tope máximo {tope_maximo} para el producto {product_id.default_code} en la compañía {self.env.company.name}")
        
        stock_final = min(stock_atp, tope_maximo)
        
        return stock_final


    @api.model
    def _build_variant_name(self, product_product_ids):
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
        
        # Obtener stock usando la ubicación configurada en la empresa
        stock = self._get_fenicio_stock(product_id)

        # Obtener listas de precio de la compañía
        listaVenta = self.env.company.fenicio_pricelist_venta_id
        listaPrecios = self.env.company.fenicio_pricelist_lista_id
        listaAlternativo = self.env.company.fenicio_pricelist_alternativo_id

        # Obtener precio de lista
        precio_lista = 0.0
        if listaPrecios:
            try:
                precio_lista = listaPrecios._get_product_price(
                    product=product_id,
                    quantity=1.0,
                    partner=None,
                    uom_id=product_id.uom_id.id
                )
            except Exception as e:
                precio_lista = product_id.lst_price or 0.0

        # Obtener precio de venta
        precio_venta = 0.0
        if listaVenta:
            try:
                precio_venta = listaVenta._get_product_price(
                    product=product_id,
                    quantity=1.0,
                    partner=None,
                    uom_id=product_id.uom_id.id
                )
            except Exception as e:
                precio_venta = product_id.lst_price or 0.0

        # Obtener precio alternativo
        precio_alternativo = 0.0
        if listaAlternativo:
            try:
                precio_alternativo = listaAlternativo._get_product_price(
                    product=product_id,
                    quantity=1.0,
                    partner=None,
                    uom_id=product_id.uom_id.id
                )
            except Exception as e:
                precio_alternativo = product_id.lst_price or 0.0

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

        # Obtener código de moneda
        currency_code = self.env.company.currency_id.name
        
        return {
            'codigo': codigo,
            'nombre': nombre_presentacion,
            'sku': product_id.default_code or '',
            'stock': stock,
            'precioLista': {currency_code: precio_lista},
            'precioVenta': {currency_code: precio_venta},
            'precioAlternativo': {currency_code: precio_alternativo},
            'identificadores': identificadores, 
        }
    

    @api.model
    def canjear_puntos(self, json_data): 
        try:

            if 'numeroDocumento' not in json_data or 'puntos' not in json_data:
                message = "El campo 'numeroDocumento' y 'puntos' es obligatorio."
                return False, message;

            user = self.env['res.partner'].search([('vat', '=', json_data['numeroDocumento'])], limit=1);
        
            if not user:
                message = "El usuario no existe."
                return False, message;
    
            loyaltyCard = self.env['loyalty.card'].search([('partner_id', '=', user.id)], limit=1);
            if not loyaltyCard:
                message = "El usuario no tiene una tarjeta de lealtad."
                return False, message;
    
            if loyaltyCard.points < float(json_data['puntos']):
                message = "El usuario no tiene suficientes puntos para canjear."
                return False, message;
    
            if loyaltyCard.points >= float(json_data['puntos']):
                loyaltyCard.points -= float(json_data['puntos'])

            return {
                'puntosRestantes': loyaltyCard.points
            }

        except Exception as e:
            return False


    @api.model
    def consultar_puntos(self, json_data):
        try:
            if 'numeroDocumento' not in json_data:
                message = "El campo 'numeroDocumento' es obligatorio."
                return False, message;

            user = self.env['res.partner'].search([('vat', '=', json_data['numeroDocumento'])], limit=1);

            if not user:
                message = "El usuario no existe."
                return False, message;

            
            loyaltyCard = self.env['loyalty.card'].search([('partner_id', '=', user.id)], limit=1);
            puntos = loyaltyCard.points if loyaltyCard else 0

            return {
                "puntos": puntos
            };

        except Exception as e:
            return False

    @api.model
    def crear_usuario(self, json_data):
        try:

            user = self.env['res.partner'].search([('id_fenicio', '=', json_data['id'])], limit=1);
            pais = self.env['res.country'].search([('code', '=', json_data['documento']['pais'])], limit=1);

            
            # VAT código 0
            # RUC código 2
            # CI código 3
            # OTROS código 4

            tipo_doc = '';
            if json_data['documento']['tipo'] == '0':
                tipo_doc = 'VAT'
            elif json_data['documento']['tipo'] == '2':
                tipo_doc = 'RUC'
            elif json_data['documento']['tipo'] == '3':
                tipo_doc = 'CI'
            elif json_data['documento']['tipo'] == '4':
                tipo_doc = 'OTROS'

            tipoDocumento = self.env['l10n_latam.identification.type'].search([('name', '=', tipo_doc), ('active', '=', True)], limit=1);

            genero = '';

            if json_data['genero'] and (json_data['genero'] == 'MASCULINO' or json_data['genero'] == 'Masculino' or json_data['genero'] == 'M'):
                genero = 'male';
            elif json_data['genero'] and (json_data['genero'] == 'FEMENINO' or json_data['genero'] == 'Femenino' or json_data['genero'] == 'F'):
                genero = 'female';
            elif json_data['genero'] and (json_data['genero'] == 'OTRO' or json_data['genero'] == 'Otro' or json_data['genero'] == 'O'):
                genero = 'other';
            
            city = 'No definida';
            if json_data['documento']['ciudad']:
                city = self.env['res.country.city'].search([('name', '=', json_data['documento']['ciudad'])], limit=1);

            # Por esto:
            city = 'No definida'
            if json_data.get('documento', {}).get('ciudad'):
                city = json_data['documento']['ciudad']
                city = self.env['res.country.city'].search([('name', '=', city)], limit=1)

            
            if user:
                message = "El usuario ya existia, no se han insertado los datos."
                return user.id_fenicio, message;
            user = self.env['res.partner'].create({
                'id_fenicio': json_data['codigo'],
                'name': json_data['nombre'] + ' ' + json_data['apellido'],
                'email': json_data['email'],
                'phone': json_data['telefono'],
                'gender': genero,
                'l10n_latam_identification_type_id': tipoDocumento.id if tipoDocumento else False,
                'vat': json_data['documento']['numero'],
                'country_id': pais.id if pais else '',
                'city_id': city.id if city else '',
                'company_id': self.env.company.id,
                'programa_millas': json_data['extras']['programaMillas']
            })


            return user.id_fenicio, "El usuario se ha creado correctamente.";
            


        except Exception as e:
            return False

    @api.model
    def stockporsku(self, json_data, token):
        skus_pedido = json_data.get('skus', [])
        vals_list = []
        sku_no_encontrados = []

        for sku in skus_pedido:
            if not sku:
                continue
            
            sku = str(sku).strip()
            product_id = self.env['product.product'].search([
                '|', '|', ('default_code', '=', sku), ('barcode', '=', sku), ('code_e_fenicio', '=', sku)
            ], limit=1)

            if not product_id:
                sku_no_encontrados.append(sku)
                continue

            stock_total = self._get_fenicio_stock(product_id, token)
            _logger.info("SKU: %s - STOCK TOTAL %s", sku, stock_total)
            
            vals_list.append({
                "sku": product_id.default_code or sku,
                "stock": stock_total,
            })

        response = {
            'stockPorSku': vals_list,
        }

        msg = ''
        if sku_no_encontrados:
            msg = f'Los siguientes sku no fueron encontrados: {sku_no_encontrados}'

        return response, msg

    @api.model
    def crear_orden_venta(self, json_data, token):
        estados = ['EN_CURSO', 'APROBADA', 'ABANDONADA', 'PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'CANCELADA']
        

        fenicio_compania = self.env.company
        
        # verificar que sea un estado valido
        if 'estado' not in json_data or json_data['estado'] not in estados:
            return {'error': 'Estado de la orden no válido'}
        try:

            estado = json_data['estado']
            id_orden_fenicio = json_data['idOrden']

            SALE_ORDER_ENV = self.env['sale.order']
            sale_order_id = SALE_ORDER_ENV.search([('id_order_fenicio', '=', id_orden_fenicio), ('company_id', '=', fenicio_compania.id)], limit=1)

            is_new_order = False


            error = ''
            if sale_order_id and sale_order_id.state == 'draft' and estado == 'EN_CURSO':
                sale_order_id, error = sale_order_id.create_or_update_order(json_data, token)
            elif not sale_order_id:
                sale_order_id, error = SALE_ORDER_ENV.create_or_update_order(json_data, token)
                is_new_order = True

                # si no se pudo crear la orden: lanzar error para rollback
                if not sale_order_id:
                    return {'error': error or "No se pudo crear la orden de venta"}

            if estado in ['PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'APROBADA']:
                if sale_order_id.state in ['draft', 'sent']:
                    sale_order_id.action_confirm()

                # si no es recien creada la orden: actualizar los datos de fenicio
                if not is_new_order:
                    sale_order_id.update_fenicio(json_data)

            cancelable = False
            if estado in ['ABANDONADA', 'CANCELADA']:
                cancelable = True

            
            if cancelable:
                invoices_ids = sale_order_id.invoice_ids
                picking_ids = sale_order_id.picking_ids

                ids_payment = []
                for invoice_id in invoices_ids:
                    reconciled_invoices_partials = invoice_id._get_reconciled_invoices_partials()
                    ids_payment += list(map(lambda l: l[2].payment_id and l[2].payment_id.id or False, reconciled_invoices_partials))

                payment_ids = self.env['account.payment'].search([('id', 'in', ids_payment)])
                payment_ids.action_draft()
                payment_ids.action_cancel()

                
                invoices_ids.crear_nota_credito()

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
                raise UserError(picking_error)

            if estado in ['PAGO_PENDIENTE', 'REQUIERE_APROBACION', 'APROBADA']:
                
                if len(sale_order_id.invoice_ids) == 0:
                    if not sale_order_id.create_invoice_fenicio():
                        raise UserError("No se pudo crear la factura para la orden")
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
                        payment_ids = invoice_id.payment_ids

                        if invoice_id.amount_residual == 0:
                            _logger.info(
                                "Factura %s ya tiene saldo 0, se omite el registro de pago.",
                                invoice_id.name
                            )
                            continue

                        invoice_id.create_payment_fenicio(json_data_pago, mode_update=(len(payment_ids) > 0), payment_ids=payment_ids)


                if estado == 'APROBADA' and sale_order_id.invoice_ids:
                    transaction_result = sale_order_id.create_payment_transaction(json_data)
                    # Si hay error en la transacción, lanzar error para rollback total
                    if 'error' in transaction_result:
                        raise UserError(transaction_result['error'])
            
            return {
                'referencia': sale_order_id.display_name,
                'mensaje': 'Orden de venta procesada exitosamente',
                'estado': estado
            }
        except Exception as e:
            _logger.error("Error al crear o actualizar la orden de venta: %s", str(e))
            raise ValidationError(str(e)) 

    @api.model
    def puede_cancelar(self, json_data):
        SALE_ORDER_ENV = self.env['sale.order']
        cancelable, error = SALE_ORDER_ENV.is_cancelable(json_data['idOrden'])

        return {
            'permiteCancelar': cancelable,
            'motivoRechazo': error
        }
