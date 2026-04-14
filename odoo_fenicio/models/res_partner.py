# -*- coding: utf-8 -*-

from odoo import models, fields, api

import logging;

_logger = logging.getLogger(__name__);
class SaleOrder(models.Model):
    _inherit = "res.partner"

    id_fenicio = fields.Char('ID Fenicio')
    numero_doc = fields.Char('Numero Doc')
    programa_millas = fields.Char("Programa Millas");

    @api.model
    def get_partner_orden_venta(self, json_data):
        comprador = json_data['comprador']
        partner_id = self.env['res.partner'].search([
            ('vat', '=', comprador['documento']['numero'])
        ], limit=1)

        if not partner_id:
            vat = ''
            # Determinar tipo de empresa basado en tipo de documento
            tipo_doc_fenicio = comprador.get('documento', {}).get('tipo', '')
            company_type = 'company' if tipo_doc_fenicio == '2' else 'person'
            
            vals = {
                'id_fenicio': comprador['id'],
                'email': comprador['email'],
                'name': f"{comprador['nombre']} {comprador['apellido']}",
                'phone': comprador['telefono'],
                'company_type': company_type,
                'es_receptor': True if company_type == 'company' else False
            }
            if 'documento' in comprador:
                pais_id = self.env['res.country'].search([('code', '=', comprador['documento']['pais'].upper())], limit=1)
                if pais_id:
                    vals['country_id'] = pais_id.id
                    
                

                tipo_doc_fenicio = comprador['documento']['tipo']

                # _logger.info("Tipo de documento Fenicio: %s", tipo_doc_fenicio);

                # # Mapeo de tipos de documento
                # mapping_tipo_doc = {
                #     '0': 'VAT',
                #     '1': 'RUC',  # Código 1 también puede ser RUC
                #     '2': 'RUC',
                #     '3': 'CI',
                #     '4': 'OTROS',
                #     'VAT': 'VAT',
                #     'RUC': 'RUC',
                #     'DOCUMENTO_IDENTIDAD': 'CI',
                #     'CI': 'CI',
                #     'PASAPORTE': 'OTROS',
                # }

                # tipo_doc = mapping_tipo_doc.get(tipo_doc_fenicio, 'OTROS')
                # _logger.info("Tipo de documento mapeado: %s", tipo_doc);

                try:
                    tipoDocumento = self.env['l10n_latam.identification.type'].search([('codigo_fenicio', '=', tipo_doc_fenicio), ('active', '=', True)], limit=1)
                    if not tipoDocumento:
                        tipoDocumento = self.env['l10n_latam.identification.type'].search([('code', '=', '4'), ('active', '=', True)], limit=1)
                        _logger.info("Tipo de documento Fenicio '%s' no encontrado, usando OTROS (código 4)", tipo_doc_fenicio)
                    if tipoDocumento:
                        vals['l10n_latam_identification_type_id'] = tipoDocumento.id

                except Exception as e:
                    _logger.warning("No se pudo asignar tipo de documento latam: %s", str(e))

                # Tipos de documento

                # VAT código 0
                # RUC código 2
                # CI código 3
                # OTROS código 4
                vals['vat'] = comprador['documento']['numero']
                vals['numero_doc'] = comprador['documento']['numero']

            partner_id = self.env['res.partner'].create([vals])
            #partner_id.child_ids.sudo().unlink()

        entrega = json_data.get('entrega', {})
        dir_envio = entrega.get('direccionEnvio', {})
        if partner_id.city == False and 'entrega' in json_data:
            if dir_envio:
                if partner_id.country_id == False:
                    pais_nombre = dir_envio.get('pais') or comprador.get('documento', {}).get('pais')
                    pais_id = self.env['res.country'].search([('name', 'ilike', pais_nombre)], limit=1) if pais_nombre else False
                    if pais_id:
                        partner_id.country_id = pais_id.id
                        
        if 'localidad' in dir_envio:
            ciudad_nombre = dir_envio['localidad']
            
            
            # Construir dominio de búsqueda con filtros apropiados
            domain = [('name', 'ilike', ciudad_nombre)]
            
            # Si ya tenemos el país, filtrar por él
            if partner_id.country_id:
                domain.append(('country_id', '=', partner_id.country_id.id))
            
            # Buscar primero el estado si está disponible
            state_id = False
            if 'departamento' in dir_envio or 'estado' in dir_envio or 'provincia' in dir_envio:
                estado_nombre = dir_envio.get('departamento') or dir_envio.get('estado') or dir_envio.get('provincia')
                
                
                if estado_nombre and partner_id.country_id:
                    
                    state_id = self.env['res.country.state'].search([
                        ('name', 'ilike', estado_nombre),
                        ('country_id', '=', partner_id.country_id.id)
                    ], limit=1)
                    
                    if state_id:
                        partner_id.state_id = state_id.id
                        domain.append(('state_id', '=', state_id.id))
                    else:
                        # Listar estados disponibles para ese país
                        estados_disponibles = self.env['res.country.state'].search([
                            ('country_id', '=', partner_id.country_id.id)
                        ])
            
            
            
            ciudad_id = self.env['res.country.city'].search(domain, limit=1)
            
            if ciudad_id:
                
                partner_id.city_id = ciudad_id.id
                
                
                if ciudad_id.state_id and not partner_id.state_id:
                    partner_id.state_id = ciudad_id.state_id.id
            

        return partner_id

    def get_partner_invoice_address_orden_venta(self, json_data):
        """Obtener o crear dirección de facturación basada en direccionFacturacion"""
        self.ensure_one()
        partner_id = self

        partner_address_id = self.env['res.partner'].search([
            ('parent_id', '=', partner_id.id),
            ('type', '=', 'invoice'),
        ], limit=1)

        if 'direccionFacturacion' not in json_data or not json_data['direccionFacturacion']:
            return partner_address_id

        dir_fact = json_data.get('direccionFacturacion', {})

        pais_nombre = dir_fact.get('pais') or (json_data.get('comprador', {}).get('documento', {}).get('pais'))
        pais_id = self.env['res.country'].search([('name', 'ilike', pais_nombre)], limit=1) if pais_nombre else False
        
        state_id = False
        estado_nombre = dir_fact.get('estado')
        if pais_id and estado_nombre:
            state_id = self.env['res.country.state'].search([
                ('country_id', '=', pais_id.id),
                ('name', 'ilike', estado_nombre),
            ], limit=1)
            if not state_id:
                state_id = self.env['res.country.state'].create({
                    'name': estado_nombre,
                    'code': estado_nombre,
                    'country_id': pais_id.id,
                })

        # Construir street2 con número de puerta y apartamento
        street2_parts = []
        if dir_fact.get('numeroPuerta'):
            street2_parts.append(str(dir_fact.get('numeroPuerta', '')))
        if dir_fact.get('numeroApto'):
            street2_parts.append(str(dir_fact.get('numeroApto', '')))
        street2 = ' '.join(street2_parts) if street2_parts else ''

        vals = {
            'type': 'invoice',
            'name': partner_id.name,
            'partner_latitude': dir_fact.get('latitud'),
            'partner_longitude': dir_fact.get('longitud'),
            'country_id': (pais_id and pais_id.id) or False,
            'state_id': (state_id and state_id.id) or False,
            'city': dir_fact.get('localidad'),
            'street': dir_fact.get('calle'),
            'street2': street2,
            'zip': dir_fact.get('codigoPostal'),
            'comment': dir_fact.get('observaciones'),
            'parent_id': partner_id.id,
        }

        if partner_address_id:
            partner_address_id.write(vals)
            return partner_address_id

        return self.env['res.partner'].create(vals)

    def get_partner_shipping_address_orden_venta(self, json_data):
        """Obtener o crear dirección de envío basada en entrega.direccionEnvio"""
        self.ensure_one()
        partner_id = self

        partner_address_id = self.env['res.partner'].search([
            ('parent_id', '=', partner_id.id),
            ('type', '=', 'delivery'),
        ], limit=1)

        if 'entrega' not in json_data or not json_data['entrega']:
            return partner_address_id

        dir_envio = json_data.get('entrega', {}).get('direccionEnvio', {})
        
        if not dir_envio:
            return partner_address_id

        pais_nombre = dir_envio.get('pais') or (json_data.get('comprador', {}).get('documento', {}).get('pais'))
        pais_id = self.env['res.country'].search([('name', 'ilike', pais_nombre)], limit=1) if pais_nombre else False
        
        state_id = False
        estado_nombre = dir_envio.get('estado')
        if pais_id and estado_nombre:
            state_id = self.env['res.country.state'].search([
                ('country_id', '=', pais_id.id),
                ('name', 'ilike', estado_nombre),
            ], limit=1)
            if not state_id:
                state_id = self.env['res.country.state'].create({
                    'name': estado_nombre,
                    'code': estado_nombre,
                    'country_id': pais_id.id,
                })

        # Construir street2 con número de puerta y apartamento
        street2_parts = []
        if dir_envio.get('numeroPuerta'):
            street2_parts.append(str(dir_envio.get('numeroPuerta', '')))
        if dir_envio.get('numeroApto'):
            street2_parts.append(str(dir_envio.get('numeroApto', '')))
        street2 = ' '.join(street2_parts) if street2_parts else ''

        vals = {
            'type': 'delivery',
            'name': json_data.get('entrega', {}).get('destinatario') or partner_id.name,
            'partner_latitude': dir_envio.get('latitud'),
            'partner_longitude': dir_envio.get('longitud'),
            'country_id': (pais_id and pais_id.id) or False,
            'state_id': (state_id and state_id.id) or False,
            'city': dir_envio.get('localidad'),
            'street': dir_envio.get('calle'),
            'street2': street2,
            'zip': dir_envio.get('codigoPostal'),
            'comment': dir_envio.get('observaciones'),
            'parent_id': partner_id.id,
        }

        if partner_address_id:
            partner_address_id.write(vals)
            return partner_address_id

        return self.env['res.partner'].create(vals)
