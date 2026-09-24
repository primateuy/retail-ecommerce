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
        
        if endpoint:
            self._registrar_log(endpoint, request_data, response_data, status, data, mensaje)

        return request.make_response(
            json.dumps(response_data).replace('false', 'null'), 
            headers=[('Content-Type', 'application/json')]
        )

    def _registrar_log(self, endpoint, request_data, response_data, status, data, mensaje):
        """Registra la llamada en fenicio.log sin afectar nunca la respuesta HTTP.

        Se loguea aunque `request_data` esté vacío (token inválido o JSON
        malformado), guardando el body crudo. Un `{'error': ...}` en `data`
        se marca como error en el log aunque el status HTTP siga siendo 'OK':
        el contrato con Fenicio no cambia, solo la trazabilidad interna.

        Args:
            endpoint (str): ruta invocada, ej. '/orden'.
            request_data (dict): body parseado, o {} si falló antes de parsearlo.
            response_data (dict): respuesta completa que se devuelve a Fenicio.
            status (str): 'OK' o 'ERROR'.
            data (dict|list|None): campo `data` de la respuesta.
            mensaje (str): campo `mensaje` de la respuesta.
        """
        try:
            error_negocio = data.get('error') if isinstance(data, dict) else None
            is_error = status != 'OK' or bool(error_negocio)
            mensaje_error = (mensaje if status != 'OK' else error_negocio) or None

            if request_data:
                request_text = json.dumps(request_data)
            else:
                request_text = request.httprequest.get_data(as_text=True)

            company = self._get_fenicio_company()
            id_order_fenicio = None
            sale_order = None
            if isinstance(request_data, dict) and request_data.get('idOrden'):
                id_order_fenicio = str(request_data['idOrden'])
                # sudo: el env puede ser el usuario público si falló la autenticación.
                # Se busca también en errores: tras el rollback el pedido de este request
                # no existe, pero uno creado en un request anterior sí, y así queda enlazado.
                sale_order = request.env['sale.order'].sudo().search([
                    ('id_order_fenicio', '=', id_order_fenicio),
                    ('company_id', '=', company.id),
                ], limit=1)

            request.env['fenicio.log'].registrar(
                'error' if is_error else 'ok',
                request_text,
                endpoint=endpoint,
                company_id=company.id,
                mensaje=response_data,
                id_order_fenicio=id_order_fenicio,
                sale_order_id=sale_order.id if sale_order else None,
                mensaje_error=str(mensaje_error) if mensaje_error else None,
            )
        except Exception as e:
            _logger.error("Error al crear log en Fenicio: %s", str(e))

    def _get_fenicio_company(self):
        """Devuelve la compañía del sitio web dueño del token, o la del entorno.

        Returns:
            res.company: compañía a la que pertenece la llamada.
        """
        token = request.httprequest.headers.get('Token-Autenticacion-Efenicio')
        if token:
            # sudo: se consulta antes de autenticar, con el usuario público.
            website = request.env['website'].sudo().search([('fenicio_token', '=', token)], limit=1)
            if website and website.company_id:
                return website.company_id
        return request.env.company

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
        token = request.httprequest.headers.get('Token-Autenticacion-Efenicio')
        json_data = {}
        try: 
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data = request.env['api.internal'].listar_productos(json_data, token)
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
        token = request.httprequest.headers.get('Token-Autenticacion-Efenicio')
        try:
            self._authenticate_and_setup_env()
            json_data = self.get_json_data()
            id_solicitud = json_data['_idSolicitud']
            response_data, msg = request.env['api.internal'].stockporsku(json_data, token)
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
