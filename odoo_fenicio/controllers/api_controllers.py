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
        http_data = request.httprequest.get_data()
        try:
            json_data = json.loads(http_data)
        except ValueError:
            msg = 'Invalid JSON data: %r' % (http_data,)
            raise Exception(msg)

        if '_idSolicitud' not in json_data:
            raise Exception('No está presente el parámetro _idSolicitud en la petición.')

        return json_data

    @api.model
    def build_response(self, id_solicitud, data, status='OK', mensaje=None, endpoint=None, request_data=None):
        response_data = {
            'status': status,
            'mensaje': mensaje,
            '_idSolicitud': id_solicitud,
            'data': data,
        }
        
        # Guardar log si se proporcionan los datos necesarios
        if endpoint and request_data:
            try:
                request.env['fenicio.log'].sudo().create({
                    'estado': 'ok' if status == 'OK' else 'error',
                    'request': json.dumps(request_data),
                    'mensaje': json.dumps(response_data),
                    'endpoint': endpoint,
                    'company_id': request.env.company.id if status == 'OK' or (hasattr(request.env, 'company') and request.env.company) else None,
                })
            except Exception as e:
                _logger.error("Error al crear log en Fenicio: %s", str(e))

        return request.make_response(
            json.dumps(response_data).replace('false', 'null'), 
            headers=[('Content-Type', 'application/json')]
        )

    def _authenticate_and_setup_env(self):
        token = request.httprequest.headers.get('Token-Autenticacion-Efenicio')
        if not token:
            raise Exception('No se proporcionó el token de autenticación.')
        
        company = request.env['api.internal'].sudo().verificar_token(token)
        
        request.env = odoo.api.Environment(request.env.cr, SUPERUSER_ID, {
            **request.env.context,
            'allowed_company_ids': company.ids,
            'company_id': company.id,
        })
        request.update_context(allowed_company_ids=company.ids, company_id=company.id)
        return company

    @http.route('/productos', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def listar_productos(self):
        id_solicitud = ''
        json_data = {}
        try: 
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].listar_productos(json_data)
            return self.build_response(id_solicitud, response_data, endpoint='/productos', request_data=json_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/productos', request_data=json_data)
        
    @http.route('/consultapuntos', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def consultar_puntos(self):
        id_solicitud = ''
        json_data = {}
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].consultar_puntos(json_data)
            return self.build_response(id_solicitud, response_data, endpoint='/consultapuntos', request_data=json_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/consultapuntos', request_data=json_data)

    @http.route('/stockporsku', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def stock_producto(self):
        id_solicitud = ''
        json_data = {}
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data, msg = request.env['api.internal'].stockporsku(json_data)
            return self.build_response(id_solicitud, response_data, mensaje=msg, endpoint='/stockporsku', request_data=json_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/stockporsku', request_data=json_data)

    @http.route('/orden', type='http', auth='none', cors="*", csrf=False, methods=['POST'])
    def crear_orden_venta(self):
        id_solicitud = ''
        json_data = {}
        token = request.httprequest.headers.get('Token-Autenticacion-Efenicio')
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].crear_orden_venta(json_data, token)
            mensaje = response_data.get('mensaje') if isinstance(response_data, dict) else None
            data = {k: v for k, v in response_data.items() if k != 'mensaje'} if isinstance(response_data, dict) else response_data
            return self.build_response(id_solicitud, data, mensaje=mensaje, endpoint='/orden', request_data=json_data)
        except Exception as e:
            request.env.cr.rollback()
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/orden', request_data=json_data)

    @http.route('/canjepuntos', type='http', auth='none', cors="*", csrf=False, methods=['GET'])
    def canjear_puntos(self):
        id_solicitud = ''
        json_data = {}
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].canjear_puntos(json_data)
            return self.build_response(id_solicitud, response_data, endpoint='/canjepuntos', request_data=json_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/canjepuntos', request_data=json_data)

    @http.route('/usuario', type="http", auth='none', cors="*", csrf=False, methods=['POST'])
    def crear_usuario(self):
        id_solicitud = ''
        json_data = {}
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].crear_usuario(json_data)
            return self.build_response(id_solicitud, response_data, endpoint='/usuario', request_data=json_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/usuario', request_data=json_data)

    @http.route('/permitecancelar', type='http', auth='public', cors="*", csrf=False, methods=['GET'])
    def puede_cancelar(self):
        id_solicitud = ''
        json_data = {}
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].puede_cancelar(json_data)
            return self.build_response(id_solicitud, response_data, endpoint='/permitecancelar', request_data=json_data)
        except Exception as e:
            return self.build_response(id_solicitud, None, status='ERROR', mensaje=str(e), endpoint='/permitecancelar', request_data=json_data)
