# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = "res.partner"

    id_fenicio = fields.Char('ID Fenicio')
    code_fenicio = fields.Char('Código Fenicio')
    numero_doc = fields.Char('Numero Doc')

    @api.model
    def get_partner_orden_venta(self, json_data):
        comprador = json_data['comprador']
        partner_id = self.env['res.partner'].search([
            ('id_fenicio', '=', comprador['id'])
        ], limit=1)

        if not partner_id:
            vat = ''
            vals = {
                'id_fenicio': comprador['id'],
                'code_fenicio': comprador['codigo'],
                'email': comprador['email'],
                'name': f"{comprador['nombre']} {comprador['apellido']}",
                'phone': comprador['telefono'],
                'company_type': 'company',
            }
            if 'documento' in comprador:
                pais_id = self.env['res.country'].search([('code', '=', comprador['documento']['pais'].upper())], limit=1)
                if pais_id:
                    vals['country_id'] = pais_id.id
                # tipo_doc_fenicio = comprador['documento']['tipo']
                # mapping_tipo_doc = {
                #     'PASAPORTE': '5',
                #     'DOCUMENTO_IDENTIDAD': '3',
                # }
                # vals['vat'] = comprador['documento']['numero']
                vals['numero_doc'] = comprador['documento']['numero']

            partner_id = self.env['res.partner'].create([vals])
            #partner_id.child_ids.sudo().unlink()
        return partner_id

    def get_partner_invoice_address_orden_venta(self, json_data):
        self.ensure_one()
        partner_id = self

        partner_address_id = self.env['res.partner'].search([
            ('parent_id', '=', partner_id.id),
            ('type', '=', 'invoice'),
        ], limit=1)

        if 'direccionFacturacion' not in json_data or not json_data['direccionFacturacion']:
            return partner_address_id

        json_data = json_data['direccionFacturacion']

        pais_id = self.env['res.country'].search([('name', 'ilike', json_data['pais'])], limit=1)
        state_id = False
        if pais_id:
            state_id = self.env['res.country.state'].search([
                ('country_id', '=', pais_id.id),
                ('name', 'ilike', json_data['estado']),
            ], limit=1)
            if not state_id:
                state_id = self.env['res.country.state'].create({
                    'name': json_data['estado'],
                    'code': json_data['estado'],
                    'country_id': pais_id.id,
                })

        vals = {
            'type': 'invoice',
            'name': partner_id.name,
            'partner_latitude': json_data['latitud'],
            'partner_longitude': json_data['longitud'],
            'country_id': (pais_id and pais_id.id) or False,
            'state_id': (state_id and state_id.id) or False,
            'city': json_data['localidad'],
            'street': json_data['calle'],
            'street2': '%s %s' % (json_data['numeroPuerta'], json_data['numeroApto']),
            'zip': json_data['codigoPostal'],
            'comment': json_data['observaciones'],
            'parent_id': partner_id.id,
        }

        if partner_address_id:
            partner_address_id.write(vals)
            return partner_address_id

        return self.env['res.partner'].create(vals)
