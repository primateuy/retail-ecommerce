# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = "res.partner"

    id_fenicio = fields.Char('ID Fenicio')
    numero_doc = fields.Char('Numero Doc')
    programa_millas = fields.Char("Programa Millas");

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
                'email': comprador['email'],
                'name': f"{comprador['nombre']} {comprador['apellido']}",
                'phone': comprador['telefono'],
                'company_type': 'company',
            }
            if 'documento' in comprador:
                pais_id = self.env['res.country'].search([('code', '=', comprador['documento']['pais'].upper())], limit=1)
                if pais_id:
                    vals['country_id'] = pais_id.id
                tipo_doc_fenicio = comprador['documento']['tipo']
                # mapping_tipo_doc = {
                #     'PASAPORTE': '5',
                #     'DOCUMENTO_IDENTIDAD': '3',
                # }

                tipo_doc = '';
                if json_data['documento']['tipo'] == '0':
                    tipo_doc = 'VAT'
                elif json_data['documento']['tipo'] == '2':
                    tipo_doc = 'RUC'
                elif json_data['documento']['tipo'] == '3':
                    tipo_doc = 'CI'
                elif json_data['documento']['tipo'] == '4':
                    tipo_doc = 'OTROS'

                tipoDocumento = self.env['res.l10n_latam.identification.type'].search([('name', '=', tipo_doc), ('active', '=', True)], limit=1);

                # Tipos de documento

                # VAT código 0
                # RUC código 2
                # CI código 3
                # OTROS código 4
                vals['vat'] = comprador['documento']['numero']
                vals['numero_doc'] = comprador['documento']['numero']
                vals['l10n_latam_identification_type_id'] = tipoDocumento.id if tipoDocumento else False

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


        pais_id = self.env['res.country'].search([('name', 'ilike', json_data['comprador']['documento']['pais'])], limit=1)
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
            'partner_latitude': json_data['entrega']['horario']['direccionEnvio']['latitud'],
            'partner_longitude': json_data['entrega']['horario']['direccionEnvio']['longitud'],
            'country_id': (pais_id and pais_id.id) or False,
            'state_id': (state_id and state_id.id) or False,
            'city': json_data['entrega']['horario']['direccionEnvio']['localidad'],
            'street': json_data['entrega']['horario']['direccionEnvio']['calle'],
            'street2': '%s %s' % (json_data['entrega']['horario']['direccionEnvio']['numeroPuerta'], json_data['entrega']['horario']['direccionEnvio']['numeroApto']),
            'zip': json_data['entrega']['horario']['direccionEnvio']['codigoPostal'],
            'parent_id': partner_id.id,
        }

        if partner_address_id:
            partner_address_id.write(vals)
            return partner_address_id

        return self.env['res.partner'].create(vals)
