# -*- coding: utf-8 -*-

import logging
import json
import odoo

from odoo import http, api, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class ApiController(http.Controller):

    @api.model
    def get_json_data(self):
        # http_data = request.httprequest.get_data().decode(request.httprequest.charset)
        http_data = request.httprequest.get_data()
        try:
            json_data = json.loads(http_data)
        except ValueError:
            msg = 'Invalid JSON data: %r' % (http_data,)
            _logger.info('%s: %s', request.httprequest.path, msg)
            raise Exception(msg)

        if '_idSolicitud' not in json_data:
            raise Exception('No está presente el parámetro _idSolicitud en la petición.')

        return json_data

    @api.model
    def build_response(self, id_solicitud, data, status='OK', mensaje=None):
        response_data = {
            'status': status,
            'mensaje': mensaje,
            '_idSolicitud': id_solicitud,
            'data': data,
        }
        return request.make_response(json.dumps(response_data).replace('false', 'null'), headers=[('Content-Type', 'application/json')])

    @http.route('/productos', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def listar_productos(self):
        """https://developers.fenicio.help/integracion-de-comercios/servicios/productos"""
        id_solicitud = ''
        try: 
            request.env['api.internal'].verificar_token(request.httprequest.headers['Token-Autenticacion-Efenicio'])
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']

            response_data = request.env['api.internal'].sudo().listar_productos(json_data)

            return self.build_response(id_solicitud, response_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e))

    @http.route('/stockporsku', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def stock_producto(self):
        """https://comercios.fenicio.help/servicios/stock-por-sku"""
        id_solicitud = ''
        try:
            request.env['api.internal'].verificar_token(request.httprequest.headers['Token-Autenticacion-Efenicio'])
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']

            response_data, msg = request.env['api.internal'].sudo().stock_producto(json_data)

            return self.build_response(id_solicitud, response_data, mensaje=msg)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e))

    @http.route('/orden', type='http', auth='none', cors="*", csrf=False, methods=['POST'])
    def crear_orden_venta(self):
        """https://comercios.fenicio.help/servicios/registro-de-orden"""
        id_solicitud = ''
        try:
            request.env['api.internal'].verificar_token(request.httprequest.headers['Token-Autenticacion-Efenicio'])
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']

            request.env = odoo.api.Environment(request.env.cr, SUPERUSER_ID, request.env.context)
            request.update_context(**request.env.context)
            # request env needs to be able to access the latest changes from the auth layers
            request.env.cr.commit()
            response_data = request.env['api.internal'].sudo().crear_orden_venta(json_data)

            return self.build_response(id_solicitud, response_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e))

    @http.route('/permitecancelar', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def puede_cancelar(self):
        """https://comercios.fenicio.help/servicios/permiso-para-cancelacion"""
        id_solicitud = ''
        try:
            request.env['api.internal'].verificar_token(request.httprequest.headers['Token-Autenticacion-Efenicio'])
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']

            response_data = request.env['api.internal'].sudo().puede_cancelar(json_data)

            return self.build_response(id_solicitud, response_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e))
