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

    @api.model
    def create_or_update_order(self, json_data):
        partner_id = self.env['res.partner'].get_partner_orden_venta(json_data)
        partner_address_id = partner_id.get_partner_invoice_address_orden_venta(json_data)

        tarifa_id = self.env['product.pricelist'].search([
            ('e_fenicio', '=', True),
            ('currency_id.name', '=', json_data['pago']['moneda']),
        ])

        if not tarifa_id:
            return False, 'No se encuentra lista de precios para la moneda {}'.format(json_data['pago']['moneda']);

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
            return False, validate_qty

        if 'lineas' in json_data['entrega']:
            for line_data in json_data['entrega']['lineas']:
                product_id = self.env['product.product'].search([('default_code', '=', line_data['sku'])], limit=1)
                if not product_id:
                    return False, f'No se encuentra producto con sku {line_data["sku"]}'
                _logger.info("PRODUCTO ENCONTRADO: {}".format(product_id.name));
                vals = {
                    'product_id': product_id.id,
                    'name': product_id.name,
                    'product_uom_qty': line_data['cantidad'],
                    'price_unit': product_id.list_price,
                }
                lines.append((0, 0, vals))

                descuentos = ('descuentos' in line_data and line_data['descuentos']) or []

                producto_decuentos_id = self.env['product.product'].search([
                    ('product_tmpl_id.fenicio_check', '=', True),
                ], limit=1)

                if len(descuentos) > 0 and not producto_decuentos_id:
                    return False, 'No se encuentra configurado un producto para registrar descuentos'

                for descuento in descuentos:
                    vals = {
                        'product_id': producto_decuentos_id.id,
                        'name': '%s - %s' % (descuento['nombre'], descuento['origen']),
                        'product_uom_qty': 1,
                        'price_unit': -abs(descuento['monto']),
                        'tax_id': False,
                    }
                    lines.append((0, 0, vals))
        company_id = self.env['res.company'].search([], limit=1)
        vals = {
            'id_order_fenicio': json_data['idOrden'],
            'estado': json_data['estado'],
            'partner_id': partner_id.id,
            'partner_invoice_id': partner_id.id,
            'partner_shipping_id': partner_address_id and partner_address_id.id or partner_id.id,
            'pricelist_id': tarifa_id.id,
            'motivo_cancelacion': json_data['motivoCancelacion'],
            'origen': json_data['origen'],
            'date_order': self.convert_datetime(date_order),
            'fecha_abandono': fecha_abandono,
            'fecha_recuperada': fecha_recuperada,
            'fecha_cancelada': self.convert_datetime(fecha_cancelada),
            'effective_date': self.convert_datetime(effective_date),
            'observaciones': json_data['entrega']['horario']['direccionEnvio']['observaciones'],
            'order_line': lines,
            'company_id': company_id.id,
        }

        _logger.info('ID: {}'.format(self.id))

        if not self.id:
            # crear la nueva orden
            return self.env['sale.order'].create([vals]), ''
        else:
            # actualizar la orden
            wrote = self.write(vals)
            # retornar error si la orden no fue actualizada
            if not wrote:
                return False, {'error': 'No se pudo actualizar el estado de la orden'}
            # retornar la orden actualizada
            return self.search([('id_order_fenicio', '=', json_data['idOrden'])], limit=1), ''

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
            _logger.info("ANTES DE CREAR FACTURA EN LA FUNCION ORIGINAL");
            modal_sale_invoice = self.env['sale.advance.payment.inv'].with_context(active_ids=[self.id]).create({
                'deduct_down_payments': True,
                'has_down_payments': False,
            })
            _logger.info("ANTES DE CREAR FACTURA EN LA FUNCION ORIGINAL x2");
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
        action = self.button_validate()
        # wizard_id = self.env['stock.immediate.transfer'].with_context(**action['context']).create({})
        # wizard_id.process()

    def actualizar_pickings(self, json_entrega_data):
        date_order = parse(json_entrega_data['horario']['hasta']) if json_entrega_data['horario'] else False
        for rec in self:
            if rec.state == 'done':
                continue

            vals = {
                'tipo': json_entrega_data['tipo'],
                'estado': json_entrega_data['estado'],
                'local': json_entrega_data['horario']['local'],
            }
            if date_order:
                vals['scheduled_date'] = self.convert_datetime(date_order)

            rec.write(vals)

            if rec.estado in ['EN_TRANSITO', 'ENTREGADO', 'RECIBIDO'] or not rec.estado:
                rec.auto_validate()
