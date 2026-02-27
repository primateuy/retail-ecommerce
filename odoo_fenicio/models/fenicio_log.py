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
    mensaje = fields.Text(string='Mensaje / Respuesta')
    endpoint = fields.Char(string='Endpoint')
    estado = fields.Selection([
        ('ok', 'Exitoso'),
        ('error', 'Error'),
    ], string='Estado', required=True, default='ok')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)

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
                continue
            try:
                data = json_lib.loads(rec.mensaje)
                rec.mensaje_pretty = json_lib.dumps(data, indent=2, ensure_ascii=False)
            except Exception:
                rec.mensaje_pretty = rec.mensaje

    @api.model
    def registrar(self, estado, request, endpoint=None, company_id=None, mensaje=None):
        """Método utilitario para crear un log desde cualquier parte del módulo."""
        self.sudo().create({
            'estado': estado,
            'request': request,
            'mensaje': mensaje or '',
            'endpoint': endpoint or '',
            'company_id': company_id or self.env.company.id,
        })
