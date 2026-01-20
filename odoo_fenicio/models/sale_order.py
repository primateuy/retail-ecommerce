# -*- coding: utf-8 -*-

import logging

import pytz
from dateutil.parser import parse
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    id_order_fenicio = fields.Char('ID Orden')
    motivo_cancelacion = fields.Char('Motivo Cancelación')
    origen = fields.Char('Origen')
    fecha_abandono = fields.Datetime('Fecha Abandono')
    fecha_recuperada = fields.Datetime('Fecha Recuperada')
    fecha_cancelada = fields.Datetime('Fecha Cancelada')
    observaciones = fields.Text('Observaciones')
    estado = fields.Char('Estado')

    @api.model
    def convert_datetime(self, datetime_object, str=True):
        dtime = datetime_object.astimezone(pytz.timezone('America/Montevideo'))
        if str:
            return dtime.strftime('%Y-%m-%d %H:%M:%S')
        return datetime_object.astimezone(pytz.timezone('America/Montevideo'))

    @api.model
    def update_fenicio(self, json_data):

        json_fecha_abandono = json_data['fechaAbandono']
        fecha_abandono = False
        if json_fecha_abandono is not None:
            fecha_abandono = self.convert_datetime(parse(json_fecha_abandono))

        json_fecha_recuperada = json_data['fechaRecuperada']
        fecha_recuperada = False
        if json_fecha_recuperada is not None:
            fecha_recuperada = self.convert_datetime(parse(json_fecha_recuperada))

        fecha_cancelada = parse(json_data['fechaFin'])

        vals = {
            'motivo_cancelacion': json_data['motivoCancelacion'],
            'origen': json_data['origen'],
            'estado': json_data['estado'],
            'fecha_abandono': fecha_abandono,
            'fecha_recuperada': fecha_recuperada,
            'fecha_cancelada': self.convert_datetime(fecha_cancelada),
        }

        self.write(vals)

    def create_payment_transaction(self, json_data):
        """Crear transacción de pago para la orden"""
        try:
            self.ensure_one()
            
            if not ('pago' in json_data and json_data['pago']):
                _logger.warning("No hay datos de pago para crear transacción")
                return {'error': 'No hay datos de pago', 'transaccion': False}
            
            json_data_pago = json_data['pago']
            id_externo = json_data_pago.get('idExterno')
            
            # Verificar si ya existe una transacción con ese ID externo
            existing_transaction = self.env['payment.transaction'].search([
                ('reference', '=', id_externo)
            ], limit=1)
            
            if existing_transaction:
                msg = f"Ya existe una transacción de pago con el ID externo: {id_externo}"
                _logger.warning(msg)
                return {'error': msg, 'transaccion': existing_transaction.id}
            
            # Obtener proveedor de pago Fenicio
            provider = self.env['payment.provider'].search([('name', '=', 'Fenicio')], limit=1)
            if not provider:
                _logger.error("No se encontró proveedor de pago Fenicio")
                return {'error': 'Proveedor de pago Fenicio no encontrado', 'transaccion': False}
            
            # Obtener moneda
            currency = self.env['res.currency'].search([('name', '=', json_data_pago.get('moneda', 'UYU'))], limit=1)
            if not currency:
                currency = self.env['res.currency'].search([('name', '=', 'UYU')], limit=1)
            
            # Buscar el payment de la factura
            payment_id = False
            if self.invoice_ids:
                # Obtener la primera factura
                invoice = self.invoice_ids[0]
                
                payment_id = self.env['account.payment'].search([
                    ('ref', '=', invoice.name)
                ], limit=1)

                
            
            # Crear transacción de pago
            transaction = self.env['payment.transaction'].create({
                'reference': id_externo,
                'amount': float(json_data_pago.get('importe', 0)),
                'currency_id': currency.id,
                'partner_id': self.partner_id.id,
                'provider_id': provider.id,
                'payment_method_id': self.env['payment.method'].search([('name', '=', 'Fenicio')], limit=1).id,
                'payment_id': payment_id.id if payment_id else False,  # ← El ID del payment de la factura
                'state': 'done' if json_data_pago.get('estado') in ['APROBADO', 'CANCELADO'] else 'pending',
                'sale_order_ids': [(6, 0, [self.id])],
            })
            
            return {'mensaje': 'Transacción de pago creada correctamente', 'transaccion': transaction.id}
            
        except Exception as e:
            _logger.error("Error al crear transacción de pago: %s", str(e))
            return {'error': f'Error al crear transacción de pago: {str(e)}', 'transaccion': False}


    @api.model
    def create_or_update_order(self, json_data):
        try:
            
            partner_id = self.env['res.partner'].sudo().with_context(skip_vat_check=True).get_partner_orden_venta(json_data)
            if not partner_id:
                return False, "Error: No se pudo crear o obtener el cliente"
            
            # Obtener dirección de facturación (basada en direccionFacturacion)
            partner_invoice_id = partner_id.get_partner_invoice_address_orden_venta(json_data)
            
            # Obtener dirección de envío (basada en entrega.direccionEnvio)
            partner_shipping_id = partner_id.get_partner_shipping_address_orden_venta(json_data)
            

            tarifa_id = self.env['product.pricelist'].search([
                ('e_fenicio', '=', True),
                ('currency_id.name', '=', json_data['pago']['moneda']),
            ])

            if not tarifa_id:
                error_msg = f"No se encuentra lista de precios para la moneda {json_data['pago']['moneda']}"
                _logger.error(error_msg)
                return False, error_msg

            
            date_order = parse(json_data['fechaInicio'])

            json_fecha_abandono = json_data['fechaAbandono']
            fecha_abandono = False
            if json_fecha_abandono is not None:
                fecha_abandono = self.convert_datetime(parse(json_fecha_abandono))

            json_fecha_recuperada = json_data['fechaRecuperada']
            fecha_recuperada = False
            if json_fecha_recuperada is not None:
                fecha_recuperada = self.convert_datetime(parse(json_fecha_recuperada))

            fecha_cancelada = parse(json_data['fechaFin'])
            effective_date = parse(json_data['fechaFin'])

            lines = []
            # eliminar cualquier linea anteriormente creada
            if self.id and len(self.order_line) != 0:
                self.write({'order_line': [(5,)]})

            
            validate_qty = self.validate_qty(json_data)
            if validate_qty:
                _logger.error("Error en validación de cantidades: %s", validate_qty)
                return False, validate_qty

            
            if 'lineas' in json_data:
                for idx, line_data in enumerate(json_data['lineas']):
                    try:
                        product_id = self.env['product.product'].search([('default_code', '=', line_data['sku'])], limit=1)
                        if not product_id:
                            error_msg = f"No se encuentra producto con sku {line_data['sku']}"
                            _logger.error(error_msg)
                            return False, error_msg
                        
                        
                        
                        # Obtener el precio y aplicar descuentos si existen
                        precio_unitario = product_id.list_price
                        descuentos = ('descuentos' in line_data and line_data['descuentos']) or []
                        
                        # Si hay descuentos, restar el total de descuentos del precio
                        if descuentos:
                            total_descuentos = sum(d.get('monto', 0) for d in descuentos)
                            precio_unitario = max(0, precio_unitario - total_descuentos)
                        
                        vals = {
                            'product_id': product_id.id,
                            'name': product_id.name,
                            'product_uom_qty': line_data['cantidad'],
                            'price_unit': precio_unitario,
                        }
                        lines.append((0, 0, vals))
                    except Exception as e:
                        error_msg = f"Error procesando línea {idx}: {str(e)}"
                        _logger.error(error_msg)
                        return False, error_msg

            

            # Obtener observaciones de forma segura
            entrega = json_data.get('entrega') or {}
            horario = entrega.get('horario') or {}
            direccion_envio = horario.get('direccionEnvio') or {}
            observaciones = direccion_envio.get('observaciones', '')

            

            journal_id = self.env['account.journal'].search([('code', '=', 'fenv')], limit=1)
            company_id = self.env['res.company'].search([], limit=1)
            vals = {
                'id_order_fenicio': json_data['idOrden'],
                'estado': json_data['estado'],
                'partner_id': partner_id.id,
                'partner_invoice_id': partner_invoice_id and partner_invoice_id.id or partner_id.id,
                'partner_shipping_id': partner_shipping_id and partner_shipping_id.id or partner_id.id,
                'pricelist_id': tarifa_id.id,
                'motivo_cancelacion': json_data['motivoCancelacion'],
                'origen': json_data['origen'],
                'date_order': self.convert_datetime(date_order),
                'fecha_abandono': fecha_abandono,
                'journal_id': journal_id.id,
                'fecha_recuperada': fecha_recuperada,
                'fecha_cancelada': self.convert_datetime(fecha_cancelada),
                'effective_date': self.convert_datetime(effective_date),
                'observaciones': observaciones,
                'order_line': lines,
                'company_id': company_id.id,
            }

            # Crear o actualizar orden
            if not self.id:
                try:
                    order = self.env['sale.order'].create([vals])

                    return order, ''
                except Exception as e:
                    error_msg = f"Error al crear la orden: {str(e)}"
                    _logger.error(error_msg)
                    return False, error_msg
            else:
                try:
                    wrote = self.write(vals)
                    if not wrote:
                        error_msg = "No se pudo actualizar el estado de la orden"
                        _logger.error(error_msg)
                        return False, error_msg
                    return self.search([('id_order_fenicio', '=', json_data['idOrden'])], limit=1), ''
                except Exception as e:
                    error_msg = f"Error al actualizar la orden: {str(e)}"
                    _logger.error(error_msg)
                    return False, error_msg
                    
        except Exception as e:
            error_msg = f"Error general en create_or_update_order: {str(e)}"
            _logger.error(error_msg)
            return False, error_msg

    @api.model
    def is_cancelable(self, order_id):
        sale_order = self.env['sale.order'].search([
            ("id_order_fenicio", "=", order_id)
        ], limit=1)

        if not sale_order:
            return False, "La orden no se encuentra registrada en Odoo"

        for picking in sale_order.picking_ids:
            if picking.state == "done":
                return False, "La orden ya fue despachada."

        if sale_order.state == "cancel":
            return False, "La orden ya fue cancelada"

        return True, None

    def actualizar_pickings(self, json_data):
        validate_qty = self.validate_qty(json_data)
        if validate_qty:
            return validate_qty
        self.picking_ids.actualizar_pickings(json_data['entrega'])

    def validate_qty(self, json_data):

        if 'entrega' in json_data:
            estado_entrega = json_data['entrega']['estado']
        else:
            estado_entrega = False

        invalid_sku = []
        if 'lineas' in json_data:
            for line_data in json_data['lineas']:
                product_id = self.env['product.product'].search([('default_code', '=', line_data['sku'])], limit=1)
                if not product_id:
                    continue

                if estado_entrega in ['EN_TRANSITO', 'ENTREGADO'] and line_data['cantidad'] > product_id.qty_available:
                    invalid_sku.append(line_data['sku'])
                    continue

        if len(invalid_sku) != 0:
            return 'No se puede validar la entrega, no existe disponibilidad para los siguientes SKUs: {}'.format(
                self.list_to_string(invalid_sku))

        return False

    @staticmethod
    def list_to_string(array):
        chain = ""
        for i in range(len(array)):
            if i != 0:
                chain += ', '
            chain += array[i]
        return chain

    def create_invoice_fenicio(self):

        try:
            self.ensure_one()
            
            # Obtener el website_id desde la configuración de Fenicio
            fenicio_website_id_str = self.env['ir.config_parameter'].sudo().get_param('odoo_fenicio.website_id')
            

            if not fenicio_website_id_str:
                _logger.error("No está configurado el sitio web de Fenicio en la configuración.");
                return False;

            fenicio_website_id = int(fenicio_website_id_str)
            self.write({'website_id': fenicio_website_id});


            
            modal_sale_invoice = self.env['sale.advance.payment.inv'].with_context(active_ids=[self.id]).create({
                'deduct_down_payments': True,
                'has_down_payments': False,
            })
            modal_sale_invoice.with_context(active_ids=[self.id]).create_invoices()
            return True
        except Exception as e:
            _logger.error("Error al crear la factura: %s", str(e))
            return False


class StockPicking(models.Model):
    _inherit = "stock.picking"

    tipo = fields.Char('Tipo de entrega')
    estado = fields.Char('Estado entrega')
    local = fields.Char('Local')

    @api.model
    def convert_datetime(self, datetime_object, str=True):
        dtime = datetime_object.astimezone(pytz.timezone('America/Montevideo'))
        if str:
            return dtime.strftime('%Y-%m-%d %H:%M:%S')
        return datetime_object.astimezone(pytz.timezone('America/Montevideo'))

    def auto_validate(self):
        self.ensure_one()
        try:
            if self.state in ['confirmed', 'waiting']:
                immediate_transfer_wizard = self.env['stock.immediate.transfer'].with_context(active_ids=[self.id]).create({})
                immediate_transfer_wizard.process()
            else:
                action = self.button_validate()
                if action and isinstance(action, dict) and 'context' in action:
                    immediate_transfer_wizard = self.env['stock.immediate.transfer'].with_context(**action['context']).create({})
                    immediate_transfer_wizard.process()
        except Exception as e:
            _logger.warning("No se pudo validar automáticamente el traslado: %s", str(e))

    def actualizar_pickings(self, json_entrega_data):
        horario = json_entrega_data.get('horario')
        date_order = parse(horario['hasta']) if horario else False
        for rec in self:
            if rec.state == 'done':
                continue

            vals = {
                'tipo': json_entrega_data.get('tipo', ''),
                'estado': json_entrega_data.get('estado', ''),
            }
            if horario:
                vals['local'] = horario.get('local', '')
            
            if date_order:
                vals['scheduled_date'] = self.convert_datetime(date_order)

            rec.write(vals)

            if rec.estado in ['EN_TRANSITO', 'ENTREGADO', 'RECIBIDO'] or not rec.estado:
                rec.auto_validate()
