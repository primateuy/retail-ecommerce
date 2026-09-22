# -*- coding: utf-8 -*-

import json as json_lib
from odoo import models, fields, api


class FeniciLog(models.Model):
    _name = 'fenicio.log'
    _description = 'Log de Integración Fenicio'
    _order = 'fecha desc'
    _rec_name = 'fecha'

    fecha = fields.Datetime(string='Fecha y Hora', required=True, default=fields.Datetime.now)
    request = fields.Text(string='Request')
    mensaje = fields.Json(string='Mensaje / Respuesta')
    endpoint = fields.Char(string='Endpoint')
    estado = fields.Selection([
        ('ok', 'Exitoso'),
        ('error', 'Error'),
    ], string='Estado', required=True, default='ok')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    # index: la búsqueda/agrupación por orden Fenicio es el uso principal de estos logs.
    id_order_fenicio = fields.Char(string='ID Orden Fenicio', index=True)
    sale_order_id = fields.Many2one('sale.order', string='Pedido de venta', ondelete='set null')
    mensaje_error = fields.Text(string='Detalle del error')

    # Campo para vista lista: preview corto del request
    request_preview = fields.Char(
        string='Request (Preview)',
        compute='_compute_request_preview',
        store=False,
    )

    # Campo para formulario: JSON formateado con indentación (Request)
    request_pretty = fields.Text(
        string='Request JSON',
        compute='_compute_request_pretty',
        store=False,
    )

    # Campo para formulario: JSON formateado con indentación (Respuesta)
    mensaje_pretty = fields.Text(
        string='Respuesta JSON',
        compute='_compute_mensaje_pretty',
        store=False,
    )

    @api.depends('request')
    def _compute_request_preview(self):
        for rec in self:
            if not rec.request:
                rec.request_preview = ''
                continue
            try:
                data = json_lib.loads(rec.request)
                parts = []
                for key in ('_idSolicitud', 'idOrden', 'skus', 'numeroDocumento'):
                    if key in data:
                        val = data[key]
                        if isinstance(val, list):
                            val = ', '.join(str(v) for v in val[:3])
                        parts.append(f"{key}: {val}")
                preview = ' | '.join(parts) if parts else rec.request[:80]
            except Exception:
                preview = rec.request[:80]
            rec.request_preview = preview

    @api.depends('request')
    def _compute_request_pretty(self):
        for rec in self:
            if not rec.request:
                rec.request_pretty = ''
                continue
            try:
                data = json_lib.loads(rec.request)
                rec.request_pretty = json_lib.dumps(data, indent=2, ensure_ascii=False)
            except Exception:
                rec.request_pretty = rec.request

    @api.depends('mensaje')
    def _compute_mensaje_pretty(self):
        for rec in self:
            if not rec.mensaje:
                rec.mensaje_pretty = ''
            elif isinstance(rec.mensaje, str):
                rec.mensaje_pretty = rec.mensaje
            else:
                rec.mensaje_pretty = json_lib.dumps(rec.mensaje, indent=2, ensure_ascii=False)

    @api.model
    def registrar(self, estado, request, endpoint=None, company_id=None, mensaje=None,
                  id_order_fenicio=None, sale_order_id=None, mensaje_error=None):
        """Método utilitario para crear un log desde cualquier parte del módulo.

        `mensaje` va directo al campo Json — puede ser un dict/list (la
        respuesta cruda de una API) o un string (un resumen de texto).

        Args:
            estado (str): 'ok' o 'error'.
            request (str): body o resumen de lo recibido/enviado.
            endpoint (str): ruta o identificador del origen del log.
            company_id (int): compañía; por defecto la del entorno.
            mensaje (dict|list|str): respuesta cruda o resumen.
            id_order_fenicio (str): idOrden de Fenicio, si aplica.
            sale_order_id (int): pedido de venta vinculado, si existe.
            mensaje_error (str): mensaje de error legible, solo si estado == 'error'.

        Returns:
            fenicio.log: el registro creado.
        """
        # sudo: los logs se escriben desde endpoints públicos y desde wizards de usuarios
        # sin permisos de escritura sobre el modelo.
        return self.sudo().create({
            'estado': estado,
            'request': request,
            'mensaje': mensaje,
            'endpoint': endpoint or '',
            'company_id': company_id or self.env.company.id,
            'id_order_fenicio': id_order_fenicio or False,
            'sale_order_id': sale_order_id or False,
            'mensaje_error': mensaje_error or False,
        })
