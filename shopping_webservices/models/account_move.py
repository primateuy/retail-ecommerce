import random
import pytz
from datetime import datetime

from psycopg2 import Date
from odoo import api, fields, models
from zeep import Client
from zeep.transports import Transport
from requests import Session
from requests.auth import HTTPBasicAuth
import logging
from zeep.helpers import serialize_object
import requests;
import json;
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    payment_distribution = fields.Text(
        string='Distribución de Pagos',
        help='JSON con la distribución de pagos por método',
        store=True,
        copy=False
    )
    
    # Campos opcionales para validación
    payment_distribution_complete = fields.Boolean(
        string='Distribución Completa',
        compute='_compute_payment_distribution_complete',
        store=True
    )

    # homologacion = fields.Boolean(
    #     string="Modo Homologación", default=False);



    mostrar_botones_declaracion = fields.Boolean(
        compute='_compute_mostrar_botones_declaracion',
        store=False
    )
    


    

    @api.depends('journal_id', 'journal_id.tecnologia', 'journal_id.shopping_payment_method_ids', 'state', 'estadoEnvio')
    def _compute_mostrar_botones_declaracion(self):
        for record in self:
            record.mostrar_botones_declaracion = (
                record.state == 'posted' and
                record.journal_id.tecnologia and
                record.journal_id.shopping_payment_method_ids and
                not record.estadoEnvio == 'enviado'
            )
    
    @api.depends('payment_distribution', 'amount_total')
    def _compute_payment_distribution_complete(self):
        for record in self:
            if record.payment_distribution:
                try:
                    distribution = json.loads(record.payment_distribution)
                    total_assigned = sum(p.get('amount', 0) for p in distribution)
                    record.payment_distribution_complete = abs(total_assigned - record.amount_total) < 0.01
                except:
                    record.payment_distribution_complete = False
            else:
                record.payment_distribution_complete = False

    
    estadoEnvio = fields.Selection(
        [
            ('enviado', 'Enviado'),
            ('noenviado', 'No enviado'),
            ('error', 'Error')
        ],
        string="Estado Envío",
        default='noenviado',
        readonly=True,
        copy=False
    )
    metodoUnico = fields.Boolean(string="Método Único", default=True, compute="_computar_tipo_venta", store=True);

    logs = fields.One2many(
        'ventas.log',
        'account_move_id',
        string="Logs de Ventas Declaradas"
    )

    ultimo_error_log = fields.Text(
        string="Ultimo error",
        compute='_compute_ultimo_error_log',
        store=False
    )

    @api.depends('logs', 'logs.estado', 'logs.texto', 'estadoEnvio')
    def _compute_ultimo_error_log(self):
        for record in self:
            ultimo = record.env['ventas.log'].search(
                [('account_move_id', '=', record.id), ('estado', '=', 'error')],
                order='fecha_declaracion desc',
                limit=1
            )
            record.ultimo_error_log = ultimo.texto if ultimo else False

    x_widget_dummy = fields.Char(string="Widget Dummy", compute='_compute_widget_dummy', store=False)

    def _calcular_totales_iva(self):
        pagoTotalSinIva = 0.0
        pagoTotalConIva = 0.0

        for linea in self.invoice_line_ids:
            precio = linea.price_unit
            cantidad = linea.quantity

            if linea.tax_ids:
                tasa_include = sum(tax.amount for tax in linea.tax_ids if tax.price_include)
                tasa_exclude = sum(tax.amount for tax in linea.tax_ids if not tax.price_include)

                if tasa_include > 0:
                    base = (precio / (1 + tasa_include / 100.0)) * cantidad
                    con_iva = precio * cantidad
                else:
                    base = precio * cantidad
                    con_iva = base * (1 + tasa_exclude / 100.0)
            else:
                base = precio * cantidad
                con_iva = base

            pagoTotalSinIva += base
            pagoTotalConIva += con_iva

        return round(pagoTotalSinIva, 2), round(pagoTotalConIva, 2)
    
    def _compute_widget_dummy(self):
        for record in self:
            record.x_widget_dummy = ''

    @api.depends('journal_id.shopping_payment_method_ids')
    def _computar_tipo_venta(self):
        journal = self.journal_id

        if journal.shopping_payment_method_ids and len(journal.shopping_payment_method_ids) == 1:
            self.metodoUnico = True
        else:
            self.metodoUnico = False

    def _validar_distribucion_pagos(self):
        for record in self:
            if not record.journal_id.integracionShopping:
                continue
            metodos = record.journal_id.shopping_payment_method_ids
            if len(metodos) <= 1:
                continue
            if not record.payment_distribution:
                raise ValidationError(
                    "El diario tiene multiples metodos de pago configurados. "
                    "Debe asignar la distribucion de pagos antes de confirmar la factura."
                )
            try:
                distribucion = json.loads(record.payment_distribution)
                total_asignado = sum(p.get('amount', 0) for p in distribucion)
                if abs(total_asignado - record.amount_total) >= 0.01:
                    raise ValidationError(
                        f"La distribucion de pagos ({total_asignado:.2f}) no coincide con el total "
                        f"de la factura ({record.amount_total:.2f}). Revise los montos asignados."
                    )
            except ValidationError:
                raise
            except Exception:
                raise ValidationError(
                    "La distribucion de pagos tiene un formato invalido. Revise los valores ingresados."
                )

    def action_post(self):
        self._validar_distribucion_pagos()
        return super().action_post()


    def get_credentials(self):
        rut = self.env['res.company'].browse(self.journal_id.company_id.id).vat;

        _logger.info(f"EL RUT DE LA EMPRESA ES {rut}");
        password = self.journal_id.password;

        if not rut or not password:
            raise ValidationError("Faltan credenciales del shopping, revisa el rut y la configuración del diario")

        return str(rut), str(password)

    def _obtener_incluir_promo(self):
        try:

            
            for linea in self.invoice_line_ids:
                if linea.price_subtotal < 0:
                    return "S"
            
        except Exception as e:
            _logger.error(f"Error al verificar promoción de shopping en factura {self.id}: {str(e)}")
        return 'N'

    

    def _verificar_promocion_shopping_en_linea(self, linea):
        """
        Verifica si una línea de descuento tiene asociada una promoción de shopping.
        
        Args:
            linea: línea de factura (account.move.line)
        
        Returns:
            bool: True si tiene promocionShopping=True, False si no
        """
        # Opción 1: Si la línea tiene reward_id directamente
        if hasattr(linea, 'reward_id') and linea.reward_id:
            reward = linea.reward_id
            if hasattr(reward, 'program_id') and reward.program_id:
                if hasattr(reward.program_id, 'promocionShopping') and reward.program_id.promocionShopping:
                    return True
        
        # Opción 2: Buscar en el programa de lealtad del cupón aplicado
        if hasattr(linea, 'coupon_id') and linea.coupon_id:
            coupon = linea.coupon_id
            if coupon.program_id and hasattr(coupon.program_id, 'promocionShopping') and coupon.program_id.promocionShopping:
                return True
        
        # Opción 3: Buscar a través del producto si tiene relación con programa de lealtad
        if linea.product_id and hasattr(linea.product_id, 'loyalty_program_id'):
            program = linea.product_id.loyalty_program_id
            if program and hasattr(program, 'promocionShopping') and program.promocionShopping:
                return True
        
        return False

    def evaluarVentas(self):
        """
        Evalúa y declara todas las ventas que:
        - No han sido enviadas (ventaEnviada = False)
        - Pertenecen a un diario con integración Shopping (integracionShopping = True)
        """
        ventas = self.env['account.move'].search([
            ('estadoEnvio', '=', 'noenviado'), 
            ('journal_id.integracionShopping', '=', True),
            ('state', '=', 'posted')  # Solo facturas confirmadas
        ])

        _logger.info(f"Encontradas {len(ventas)} ventas por declarar")

        for venta in ventas:
            try:
                metodos_pago = venta.journal_id.shopping_payment_method_ids
                
                if not metodos_pago:
                    _logger.warning(f"Venta ID {venta.id}: Sin métodos de pago configurados en el diario")
                    continue
                
                # Si hay un único método, declara con ese
                if len(metodos_pago) == 1:
                    _logger.info(f"Declarando venta ID {venta.id} con método único")
                    venta.declararVentaUnicoMetodo()
                else:
                    # Si hay múltiples métodos
                    _logger.info(f"Declarando venta ID {venta.id} con múltiples métodos")
                    venta.declararVentaVariosMetodos()
                    
            except Exception as e:
                _logger.error(f"Error al declarar venta ID {venta.id}: {str(e)}", exc_info=True)
                continue


    def _now_uruguay(self):
        """Retorna la fecha/hora actual en zona horaria de Uruguay (GMT-3)."""
        tz_uruguay = pytz.timezone('America/Montevideo')
        return datetime.now(tz_uruguay)

    def _format_fecha_emision_cfe(self):
        """
        Formatea la fecha de emisión del CFE al formato YYYY-MM-DD HH:MM
        Si existe cfe_fecha_hora_firma, la usa. Si no, usa la fecha/hora actual en GMT-3.
        
        Convierte formatos como: 2026-02-06T15:14:16.0000000-03:00 → 2026-02-06 15:14
        """
        try:
            if self.cfe_fecha_hora_firma:
                # Parsear el formato ISO 8601 con timezone
                dt = datetime.fromisoformat(self.cfe_fecha_hora_firma)
                return dt.strftime('%Y-%m-%d %H:%M')
        except (ValueError, AttributeError):
            pass
        
        # Fallback: usar la fecha/hora actual en hora Uruguay (GMT-3)
        return self._now_uruguay().strftime('%Y-%m-%d %H:%M')

    
    def get_zeep_client(self, wsdl_url):
        # Ensure the URL ends with ?wsdl for proper WSDL loading
        if not wsdl_url.endswith('?wsdl'):
            # Remove any existing query parameters and add ?wsdl
            if '?' in wsdl_url:
                wsdl_url = wsdl_url.split('?')[0] + '?wsdl'
            else:
                wsdl_url = wsdl_url + '?wsdl'
        
        _logger.info("WSDL URL after validation: %s", wsdl_url)

        if self.journal_id.tecnologia == 'lecueder':

            rut, password = self.get_credentials()

            session = Session()
            session.verify = True
            session.auth = HTTPBasicAuth(rut, password)

            transport = Transport(session=session, timeout=20)

            client = Client(wsdl=wsdl_url, transport=transport)

            if client is None:
                _logger.info("No se pudo crear el cliente Zeep para Lecueder")
                return;

        elif self.journal_id.tecnologia == 'costa_urbana':

            usuario = self.journal_id.usuario
            password = self.journal_id.password
            
            if not password or not usuario:
                _logger.info("Faltan credenciales del shopping Costa Urbana")
                return;
    
            session = Session()
            session.verify = True
            session.auth = HTTPBasicAuth(usuario, password)
            transport = Transport(session=session, timeout=20)

            client = Client(wsdl=wsdl_url, transport=transport)

            if client is None:
                _logger.info("No se pudo crear el cliente Zeep para Costa Urbana")
                return;

        else:
            _logger.info("Tecnología no soportada para creación de cliente Zeep")
            return;


        return client;

    def declararVentaVariosMetodosManual(self):
        if self.state != 'posted':
            raise UserError("Solo se puede declarar una venta confirmada.")

        if not self.payment_distribution:
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'El diario tiene multiples metodos de pago configurados. Debe asignar la distribucion de pagos antes de confirmar la factura.'
            })
            self.write({'estadoEnvio': 'error'})
            self.env.cr.commit()
            raise ValidationError("El diario tiene multiples metodos de pago configurados. Debe asignar la distribucion de pagos antes de confirmar la factura.")

        try:
            distribucion = json.loads(self.payment_distribution)
            total_asignado = sum(p.get('amount', 0) for p in distribucion)
            if abs(total_asignado - self.amount_total) >= 0.01:
                self.env['ventas.log'].sudo().create({
                    'account_move_id': self.id,
                    'fecha_declaracion': fields.Datetime.now(),
                    'estado': 'error',
                    'texto': f"La distribucion de pagos ({total_asignado:.2f}) no coincide con el total de la factura ({self.amount_total:.2f}). Revise los montos asignados."
                })
                self.write({'estadoEnvio': 'error'})
                self.env.cr.commit()
                raise ValidationError(
                    f"La distribucion de pagos ({total_asignado:.2f}) no coincide con el total "
                    f"de la factura ({self.amount_total:.2f}). Revise los montos asignados."
                )
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("La distribucion de pagos tiene un formato invalido. Revise los valores ingresados.")

        tipo = self.env['account.journal'].browse(self.journal_id.id).tecnologia

        if not tipo or tipo == '':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'Falta definir la tecnología del punto de venta en el diario asociado.'
            })
            return

        if tipo == 'lecueder':
            self.declararVentaVariosMetodosLecueder()
            message_id = self.env['message.wizard'].create({'message': "Venta declarada correctamente en Lecueder. ID: %s" % self.id})
            return {
                'name': 'Resultado Declaración Venta',
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'message.wizard',
                'res_id': message_id.id,
                'target': 'new'
            }
        elif tipo == 'costa_urbana':
            self.declararVentaVariosMetodosCostaUrbana()
            message_id = self.env['message.wizard'].create({'message': "Venta declarada correctamente en Costa Urbana. ID: %s" % self.id})
            return {
                'name': 'Resultado Declaración Venta',
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'message.wizard',
                'res_id': message_id.id,
                'target': 'new'
            }
        else:
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Tecnología {tipo} no implementada aún.'
            })

    def declararVentaVariosMetodos(self):
        if self.state != 'posted':
            raise UserError("Solo se puede declarar una venta confirmada.")

        if not self.payment_distribution:
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'El diario tiene multiples metodos de pago configurados. Debe asignar la distribucion de pagos antes de confirmar la factura.'
            })
            self.write({'estadoEnvio': 'error'})
            self.env.cr.commit()
            raise ValidationError("El diario tiene multiples metodos de pago configurados. Debe asignar la distribucion de pagos antes de confirmar la factura.")

        try:
            distribucion = json.loads(self.payment_distribution)
            total_asignado = sum(p.get('amount', 0) for p in distribucion)
            if abs(total_asignado - self.amount_total) >= 0.01:
                self.env['ventas.log'].sudo().create({
                    'account_move_id': self.id,
                    'fecha_declaracion': fields.Datetime.now(),
                    'estado': 'error',
                    'texto': f"La distribucion de pagos ({total_asignado:.2f}) no coincide con el total de la factura ({self.amount_total:.2f}). Revise los montos asignados."
                })
                self.write({'estadoEnvio': 'error'})
                self.env.cr.commit()
                raise ValidationError(
                    f"La distribucion de pagos ({total_asignado:.2f}) no coincide con el total "
                    f"de la factura ({self.amount_total:.2f}). Revise los montos asignados."
                )
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("La distribucion de pagos tiene un formato invalido. Revise los valores ingresados.")

        tipo = self.env['account.journal'].browse(self.journal_id.id).tecnologia

        if not tipo or tipo == '':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'Falta definir la tecnología del punto de venta en el diario asociado.'
            })
            return

        if tipo == 'lecueder':
            self.declararVentaVariosMetodosLecueder()
        elif tipo == 'costa_urbana':
            self.declararVentaVariosMetodosCostaUrbana()
        else:
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Tecnología {tipo} no implementada aún.'
            })
            _logger.info(f"Tecnología {tipo} no implementada aún")
    
    def declararVentaVariosMetodosLecueder(self):
        """
        Declara una venta con múltiples métodos de pago (crédito, débito, contado)
        Distribuye el monto según el JSON de payment_distribution (que incluye IVA) 
        pero convierte a SIN IVA para el envío al servicio
        """
        url = self.journal_id.url;
        
        client = self.get_zeep_client(url)
        _logger.info("Cliente Zeep creado exitosamente para múltiples métodos")

        if not url:
            raise UserError("Falta URL de declaración de ventas en la configuración")

        rut = self.env['res.company'].browse(self.journal_id.company_id.id).vat;

        if not rut:
            raise UserError("Falta RUT en la configuración")

        codigoShopping = self.journal_id.codigoShopping
        numeroContrato = self.journal_id.nroContrato
        codigoCanal = self.journal_id.codigoCanal
        codigoRubro = self.journal_id.codigoRubro

        if not codigoShopping or not numeroContrato or not codigoCanal or not codigoRubro:
            raise UserError("Faltan datos del punto de venta del shopping en el diario asociado")

        # Obtener los métodos de pago configurados
        metodosPago = self.journal_id.shopping_payment_method_ids
        if not metodosPago or len(metodosPago) == 0:
            raise UserError("Debe haber al menos un método de pago configurado en el diario")
        
        # Calcular TOTALES REALES (sin IVA y con IVA) PRIMERO
        pagoTotalSinIva = 0.0
        pagoTotalConIva = 0.0
        distribucion_sin_iva = {}  # Para guardar montos sin IVA por método

        pagoTotalSinIva, pagoTotalConIva = self._calcular_totales_iva()

        # Inicializar montos por tipo de pago
        monto_contado = 0.0
        monto_credito = 0.0
        monto_debito = 0.0

        # Obtener distribución de pagos
        try:
            distribuido = json.loads(self.payment_distribution) if self.payment_distribution else []
        except:
            distribuido = []

        _logger.info("Distribución de pagos (CON IVA): %s", distribuido)

        # Procesar distribución
        if distribuido:
            # Validar que la distribución suma aproximadamente el total con IVA
            total_distribuido = sum(d.get('amount', 0.0) for d in distribuido)
            _logger.info("Total distribuido (CON IVA): %s vs Total factura (CON IVA): %s", total_distribuido, pagoTotalConIva)
            
            if abs(total_distribuido - pagoTotalConIva) > 25.0:
                _logger.warning("La distribución no coincide con el total de la factura. Diferencia: %s", 
                            total_distribuido - pagoTotalConIva)
            
            # Convertir distribución CON IVA a SIN IVA proporcionalmente
            if pagoTotalConIva > 0:
                factor_sin_iva = pagoTotalSinIva / pagoTotalConIva
                
                for pago in metodosPago:
                    asignado_con_iva = 0.0
                    
                    # Buscar el monto asignado a este método en el JSON (CON IVA)
                    for distribucion in distribuido:
                        if distribucion.get('payment_method_id') == pago.id:
                            asignado_con_iva = float(distribucion.get('amount', 0.0))
                            break
                    
                    # Convertir a SIN IVA
                    asignado_sin_iva = asignado_con_iva * factor_sin_iva
                    
                    _logger.info(f"Método {pago.name}: {asignado_con_iva} (CON IVA) → {asignado_sin_iva} (SIN IVA)")

                    if pago.esContado():
                        monto_contado += asignado_sin_iva
                    elif pago.esCredito():
                        monto_credito += asignado_sin_iva
                    elif pago.esDebito():
                        monto_debito += asignado_sin_iva
        else:
            # Si no hay distribución específica, usar el total si es un único método
            if len(metodosPago) == 1:
                monto_asignado = pagoTotalSinIva
                pago = metodosPago[0]
                
                if pago.esContado():
                    monto_contado = monto_asignado
                elif pago.esCredito():
                    monto_credito = monto_asignado
                elif pago.esDebito():
                    monto_debito = monto_asignado
                
                _logger.info(f"Método único {pago.name}: {monto_asignado} (SIN IVA)")
            else:
                self.env['ventas.log'].sudo().create({
                    'account_move_id': self.id,
                    'fecha_declaracion': fields.Datetime.now(),
                    'estado': 'error',
                    'texto': f'Debe definir la distribución de pagos cuando hay múltiples métodos de pago'
                })
                raise UserError("Debe definir la distribución de pagos cuando hay múltiples métodos de pago")

        
        codigoCFE, serieCFE, numeroCFE = '', '', '';

        if self.cfe_serie_num:
            codigoCFE, serieCFE, numeroCFE = self.cfe_serie_num.split('-');

        if self.journal_id.homologacion:
            _logger.info("Modo homologación activo");
            codigoCFE = "101"
            serieCFE = "PRU"
            numeroCFE = str(random.randint(1, 1000))  # Usar el número de factura de prueba

        
        _logger.info(f"{codigoCFE} - {serieCFE} - {numeroCFE}");

        try:
            request_data = {
                'wsDeclaVtas': {
                    'General': {
                        'Cab': {
                            'NumeroRUT': rut,
                            'CodigoShopping': codigoShopping,
                            'NumeroContrato': numeroContrato,
                            'CodigoCanal': codigoCanal,
                            'CodigoCFE': codigoCFE,
                            'NumeroCFE': numeroCFE,
                            'SerieCFE': serieCFE,
                            'MonedaCFE': 'UYU',
                            'FechaEmisionCFE': self._format_fecha_emision_cfe(),
                            'TotalMOCIVA': str(pagoTotalConIva),
                            'TotalMNSIVA': str(pagoTotalSinIva),
                            'TipodeCambio': '1'
                        },
                        'Det': {
                            'CodRubro': codigoRubro,
                            'ContadoMNSIVA': str(round(monto_contado, 2)),
                            'CreditoMNSIVA': str(round(monto_credito, 2)),
                            'DebitoMNSIVA': str(round(monto_debito, 2)),
                            'IncluirenPromo': self._obtener_incluir_promo()
                        }
                    }
                }
            }

            _logger.info("Preparando para enviar request: %s", request_data)

            response = client.service.procesarAlta(**request_data)

            _logger.info("=== RESPUESTA RECIBIDA ===")
            _logger.info("Tipo: %s", type(response))
            response_dict = serialize_object(response)
            _logger.info("Datos: %s", response_dict)

            if isinstance(response_dict, list) and len(response_dict) > 0:
                primer_resultado = response_dict[0]
                estado = primer_resultado.get('estado')
                mensaje = primer_resultado.get('mensaje', '')
                identificador = primer_resultado.get('identificador')

                if estado == 0:
                    _logger.info("=== DECLARACIÓN EXITOSA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    # Guardar que la venta fue enviada
                    self.write({
                        'estadoEnvio': 'enviado'
                    })
                    
                    self.env['ventas.log'].sudo().create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'exito',
                        'texto': f'Venta declarada correctamente. ID: {identificador}'
                    })

                    self.env.cr.commit()

                    # message_id = self.env['message.wizard'].create({'message': "Venta declarada correctamente. ID: %s" % identificador})
                    # return {
                    #     'name': 'Resultado Declaración Venta',
                    #     'type': 'ir.actions.act_window',
                    #     'view_mode': 'form',
                    #     'res_model': 'message.wizard',
                    #     'res_id': message_id.id,
                    #     'target': 'new'
                    # }

                    return;
                
                if estado == 1:
                    _logger.info("=== DECLARACIÓN PRE-GRABADA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'warning',
                        'texto': f'Venta pre-grabada. ID: {identificador}'
                    })

                    self.env.cr.commit()
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Éxito',
                            'message': f'Venta pre-grabada correctamente. ID: {identificador}',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
                
                if estado == 2:
                    try:
                        log = self.env['ventas.log'].sudo().create({
                            'account_move_id': self.id,
                            'fecha_declaracion': fields.Datetime.now(),
                            'estado': 'error',
                            'texto': f'Error al grabar: {mensaje}'
                        })

                        self.env.cr.commit()

                        _logger.info(f"Log creado con ID: {log.id}")
                    except Exception as e:
                        _logger.info(f"{e}")

                    raise UserError(f"Error al procesar el archivo (Estado {estado}): {mensaje}")
                
                if estado == 3:
                    _logger.error("=== ERROR AL PROCESAR ===")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error al procesar: {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al procesar la venta (Estado {estado}): {mensaje}")

                else:
                    _logger.error("=== DECLARACIÓN FALLIDA ===")
                    _logger.error(f"Estado: {estado}")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error al declarar la venta: {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al declarar la venta (Estado {estado}): {mensaje}")
            else:
                raise UserError("Respuesta del servicio web no válida")

        except Exception as e:
            self.write({
                'estadoEnvio': 'error'
            })
            _logger.error("Error completo: %s", str(e), exc_info=True)
            raise
        
    def declararVentaUnicoMetodoCostaUrbana(self):
        """
        Declara una venta con un único método de pago en Costa Urbana
        """
        url = self.journal_id.url;

        if not url:
            raise ValidationError("No hay url configurada.")
        
        client = self.get_zeep_client(url)
        _logger.info("Cliente Zeep creado exitosamente para Costa Urbana - Método único")

        rut = self.env['res.company'].browse(self.journal_id.company_id.id).vat
        if not rut:
            raise UserError("Falta RUT en la configuración")

        codigoShopping = self.journal_id.codigoShopping
        numeroContrato = self.journal_id.nroContrato
        codigoCanal = self.journal_id.codigoCanal
        codigoRubro = self.journal_id.codigoRubro

        if not codigoShopping or not numeroContrato or not codigoCanal or not codigoRubro:
            raise UserError("Faltan datos del punto de venta de Costa Urbana en el diario asociado")

        # Obtener el método de pago único
        metodoPago = self.journal_id.shopping_payment_method_ids
        if not metodoPago or len(metodoPago) != 1:
            raise UserError("Debe haber exactamente un método de pago configurado en el diario")
        
        metodoPago = metodoPago[0]
        
        # Determinar código de forma de pago según el tipo
        if metodoPago.esContado():
            codigoFormaPago = '00'  # Contado
        elif metodoPago.esCredito():
            codigoFormaPago = '17'  # Otros Créditos (no tarjetas)
        elif metodoPago.esDebito():
            codigoFormaPago = '91'  # Tarjetas de débito
        else:
            raise UserError("Tipo de método de pago no reconocido")

        pagoTotalSinIva, pagoTotalConIva = self._calcular_totales_iva()

        # Montos por tipo de pago
        monto_contado = str(round(pagoTotalSinIva, 2)) if metodoPago.esContado() else '0'
        monto_credito = str(round(pagoTotalSinIva, 2)) if metodoPago.esCredito() else '0'
        monto_debito = str(round(pagoTotalSinIva, 2)) if metodoPago.esDebito() else '0'

        # Datos CFE
        codigoCFE, serieCFE, numeroCFE = '', '', ''
        if self.cfe_serie_num:
            codigoCFE, serieCFE, numeroCFE = self.cfe_serie_num.split('-')

        if self.journal_id.homologacion:
            codigoCFE = "101"
            serieCFE = "PRU"
            numeroCFE = str(random.randint(1, 1000))

        try:
            fecha_emision = self._format_fecha_emision_cfe()
            fecha_transferencia = fields.Date.today().isoformat() 
            
            if self.cfe_fecha_hora_firma:
                try:
                    dt = datetime.fromisoformat(self.cfe_fecha_hora_firma)
                    hora_transferencia = dt.strftime('%H:%M')
                except (ValueError, AttributeError):
                    hora_transferencia = self._now_uruguay().strftime('%H:%M')
            else:
                hora_transferencia = self._now_uruguay().strftime('%H:%M')

            secuencial = self.journal_id.secuencial_ventas or 1
            caja = self.journal_id.caja or 1

            request_data = {
                'wsDeclaVtas': {
                    'General': {
                        'Cab': {
                            'NumeroRUT': rut,
                            'CodigoShopping': codigoShopping,
                            'NumeroContrato': numeroContrato,
                            'CodigoCanal': codigoCanal,
                            'Secuencial': secuencial,
                            'CodigoFormaPago': codigoFormaPago,
                            'Caja': caja,
                            'CodigoCFE': codigoCFE,
                            'NumeroCFE': numeroCFE,
                            'SerieCFE': serieCFE,
                            'MonedaCFE': 'UYU',
                            'FechaEmisionCFE': fecha_emision,
                            'TotalMOCIVA': str(round(pagoTotalConIva, 2)),
                            'TotalMNSIVA': str(round(pagoTotalSinIva, 2)),
                            'FechaTransferencia': fecha_transferencia,
                            'Horatransferencia': hora_transferencia,
                            'CantidadCuotas': 1
                        },
                        'Det': {
                            'CodRubro': codigoRubro,
                            'ContadoMNSIVA': monto_contado,
                            'CreditoMNSIVA': monto_credito,
                            'DebitoMNSIVA': monto_debito,
                            'IncluirenPromo': self._obtener_incluir_promo()
                        }
                    }
                }
            }

            _logger.info("REQUEST COSTA URBANA (wsDeclaVtas): %s", request_data)


            response = client.service.procesarAlta(**request_data)

            response_dict = serialize_object(response)

            if isinstance(response_dict, list) and len(response_dict) > 0:
                primer_resultado = response_dict[0]
                estado = primer_resultado.get('estado')
                mensaje = primer_resultado.get('mensaje', '')
                identificador = primer_resultado.get('identificador')

                if estado == 0:
                    
                    self.write({
                        'estadoEnvio': 'enviado'
                    })

                    self.env['ventas.log'].sudo().create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'exito',
                        'texto': f'Venta declarada correctamente en Costa Urbana. ID: {identificador}'
                    })

                    self.journal_id.write({'secuencial_ventas': secuencial + 1})

                    self.env.cr.commit()

                    return;
                
                if estado == 1:
                    _logger.info("=== DECLARACIÓN PRE-GRABADA COSTA URBANA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'warning',
                        'texto': f'Venta pre-grabada en Costa Urbana. ID: {identificador}'
                    })



                    self.journal_id.write({'secuencial_ventas': secuencial + 1})

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Éxito',
                            'message': f'Venta pre-grabada correctamente en Costa Urbana. ID: {identificador}',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
                
                if estado == 2 or estado == 3:
                    _logger.error("=== ERROR COSTA URBANA ===")
                    _logger.error(f"Estado: {estado}")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error en Costa Urbana (Estado {estado}): {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al declarar la venta en Costa Urbana (Estado {estado}): {mensaje}")
                
                else:
                    _logger.error("=== DECLARACIÓN FALLIDA COSTA URBANA ===")
                    _logger.error(f"Estado: {estado}")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error al declarar venta en Costa Urbana: {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al declarar venta en Costa Urbana: {mensaje}")
            else:
                raise UserError("Respuesta del servicio web de Costa Urbana no válida")

        except Exception as e:
            _logger.error("Error completo Costa Urbana: %s", str(e), exc_info=True)

            self.env['ventas.log'].create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Error al declarar venta en Costa Urbana: {str(e)}'
            })

            self.write({
                'estadoEnvio': 'error'
            })

            self.env.cr.commit()
            raise



    def declararVentaUnicoMetodoLecueder(self):
        url = self.journal_id.url
        
        client = self.get_zeep_client(url)

        if not url:
            raise UserError("Falta URL de declaración de ventas en la configuración")

        rut = self.env['res.company'].browse(self.journal_id.company_id.id).vat;

        _logger.info(f"EL RUT DE LA EMPRESA ES {rut}");

        if not rut:
            raise UserError("Falta el RUT de la empresa")

        codigoShopping = self.journal_id.codigoShopping
        numeroContrato = self.journal_id.nroContrato
        codigoCanal = self.journal_id.codigoCanal
        codigoRubro = self.journal_id.codigoRubro

        if not codigoShopping or not numeroContrato or not codigoCanal or not codigoRubro:
            raise UserError("Faltan datos del punto de venta del shopping en el diario asociado")

        # Obtener el método de pago UNA VEZ
        metodoPago = self.journal_id.shopping_payment_method_ids
        if not metodoPago or len(metodoPago) != 1:
            raise UserError("Debe haber exactamente un método de pago configurado en el diario")
        
        metodoPago = metodoPago[0]  # Obtener el primer (y único) método
        esContado = metodoPago.esContado()
        esCredito = metodoPago.esCredito()
        esDebito = metodoPago.esDebito()

        lineas = self.invoice_line_ids
        
        pagoTotalSinIva = 0.0
        pagoTotalConIva = 0.0

        pagoTotalSinIva, pagoTotalConIva = self._calcular_totales_iva()

        

        # Determinar el monto según el tipo de pago
        monto_contado = str(pagoTotalSinIva) if esContado else '0'
        monto_credito = str(pagoTotalSinIva) if esCredito else '0'
        monto_debito = str(pagoTotalSinIva) if esDebito else '0'
        
        codigoCFE, serieCFE, numeroCFE = '', '', '';

        if self.cfe_serie_num:
            codigoCFE, serieCFE, numeroCFE = self.cfe_serie_num.split('-');

        if self.journal_id.homologacion:
            codigoCFE = "101"
            serieCFE = "PRU"
            numeroCFE = str(random.randint(1, 1000))  # Usar el número de factura de prueba
            
        
        try:
            request_data = {
                'wsDeclaVtas': {
                    'General': {
                        'Cab': {
                            'NumeroRUT': rut,
                            'CodigoShopping': codigoShopping,
                            'NumeroContrato': numeroContrato,
                            'CodigoCanal': codigoCanal,
                            'CodigoCFE': codigoCFE,
                            'NumeroCFE': numeroCFE,  # Usar el número de factura
                            'SerieCFE': serieCFE,
                            'MonedaCFE': 'UYU',
                            'FechaEmisionCFE': self._format_fecha_emision_cfe(),
                            'TotalMOCIVA': str(pagoTotalConIva),  # ← CORREGIDO: Usar calculado
                            'TotalMNSIVA': str(pagoTotalSinIva),  # ← CORREGIDO: Usar calculado
                            'TipodeCambio': '1'
                        },
                        'Det': {
                            'CodRubro': codigoRubro,
                            'ContadoMNSIVA': monto_contado,    # ← CORREGIDO: Usar calculado
                            'CreditoMNSIVA': monto_credito,    # ← CORREGIDO: Usar calculado
                            'DebitoMNSIVA': monto_debito,      # ← CORREGIDO: Usar calculado
                            'IncluirenPromo': self._obtener_incluir_promo()
                        }
                    }
                }
            }
            
            _logger.info(f"REQUEST ENVIADA => {request_data}");

            response = client.service.procesarAlta(**request_data)

            _logger.info("=== RESPUESTA RECIBIDA ===")
            _logger.info("Tipo: %s", type(response))
            response_dict = serialize_object(response)
            _logger.info("Datos: %s", response_dict)

            


            if isinstance(response_dict, list) and len(response_dict) > 0:
                primer_resultado = response_dict[0]
                estado = primer_resultado.get('estado')
                mensaje = primer_resultado.get('mensaje', '')
                identificador = primer_resultado.get('identificador')

                if estado == 0:
                    _logger.info("=== DECLARACIÓN EXITOSA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.write({
                        'estadoEnvio': 'enviado'
                    })
                    

                    self.env['ventas.log'].sudo().create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'exito',
                        'texto': f'Venta declarada correctamente. ID: {identificador}'
                    })

                    self.env.cr.commit();

                    return;

                    
                
                if estado == 1:
                    _logger.info("=== DECLARACIÓN EXITOSA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'warning',
                        'texto': f'Venta pre-grabada. ID: {identificador}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit();
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Éxito',
                            'message': f'Venta pre-grabada correctamente. ID: {identificador}',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
                
                if estado == 2:
                    
                    try:

                        log = self.env['ventas.log'].sudo().create({
                            'account_move_id': self.id,
                            'fecha_declaracion': fields.Datetime.now(),
                            'estado': 'error',
                            'texto': f'Error al grabar: {mensaje}'
                        })

                        self.write({
                            'estadoEnvio': 'error'
                        })

                        self.env.cr.commit();

                        _logger.info(f"Log creado con ID: {log.id}");
                    except Exception as e:
                        _logger.info(f"{e}");



                    
                    raise UserError(f"Error al procesar el archivo (Estado {estado}): {mensaje}")
                
                if estado == 3:
                    _logger.error("=== ERROR AL PROCESAR ===")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error al procesar: {mensaje}'
                    })  

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit();

                    raise UserError(f"Error al procesar la venta (Estado {estado}): {mensaje}")

                else:
                    _logger.error("=== DECLARACIÓN FALLIDA ===")
                    _logger.error(f"Estado: {estado}")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error al declarar la venta: {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit();
                    
                    raise UserError(f"Error al declarar la venta (Estado {estado}): {mensaje}")
            else:
                raise UserError("Respuesta del servicio web no válida")

        except Exception as e:
            _logger.error("Error completo: %s", str(e), exc_info=True)

            self.env['ventas.log'].create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Error al declarar la venta: {str(e)}'
            })

            self.write({
                'estadoEnvio': 'error'
            })

            self.env.cr.commit()
            raise

    def declararVentaUnicoMetodo(self):
        if self.state != 'posted':
            raise UserError("Solo se puede declarar una venta confirmada.")
        tipo = self.env['account.journal'].browse(self.journal_id.id).tecnologia

        if not tipo or tipo == '':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'Falta definir la tecnología del punto de venta en el diario asociado.'
            })
            return

        if tipo == 'costa_urbana':
            self.declararVentaUnicoMetodoCostaUrbana()

            return;

        if tipo != 'lecueder':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Tecnología {tipo} no implementada aún.'
            })
            return

        self.declararVentaUnicoMetodoLecueder();
        return;

    def declararVentaUnicoMetodoManual(self):
        if self.state != 'posted':
            raise UserError("Solo se puede declarar una venta confirmada.")
        tipo = self.env['account.journal'].browse(self.journal_id.id).tecnologia

        if not tipo or tipo == '':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'Falta definir la tecnología del punto de venta en el diario asociado.'
            })
            return

        if tipo == 'costa_urbana':
            self.declararVentaUnicoMetodoCostaUrbana()

            message_id = self.env['message.wizard'].create({
                        'message': "Venta declarada correctamente en Costa Urbana. ID: %s" % self.id
                    })
            return {
                'name': 'Resultado Declaración Venta',
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'message.wizard',
                'res_id': message_id.id,
                'target': 'new'
            }

        if tipo != 'lecueder':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Tecnología {tipo} no implementada aún.'
            })
            return

        self.declararVentaUnicoMetodoLecueder();
        message_id = self.env['message.wizard'].create({'message': "Venta declarada correctamente en Lecueder. ID: %s" % self.id})
        return {
            'name': 'Resultado Declaración Venta',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'message.wizard',
            # pass the id
            'res_id': message_id.id,
            'target': 'new'
        }

        

    def declararVentaVariosMetodosCostaUrbana(self):
        """
        Declara una venta con múltiples métodos de pago en Costa Urbana usando wsDeclaVtas
        """
        url = self.journal_id.url;

        _logger.info(f"URL A UTILIZAR => {url}")

        if not url:


            raise ValidationError("No hay url configurada.")
        
        client = self.get_zeep_client(url)
        _logger.info("Cliente Zeep creado exitosamente para Costa Urbana - Múltiples métodos")

        rut = self.env['res.company'].browse(self.journal_id.company_id.id).vat
        if not rut:
            raise UserError("Falta RUT en la configuración")

        codigoShopping = self.journal_id.codigoShopping
        numeroContrato = self.journal_id.nroContrato
        codigoCanal = self.journal_id.codigoCanal
        codigoRubro = self.journal_id.codigoRubro

        if not codigoShopping or not numeroContrato or not codigoCanal or not codigoRubro:
            raise UserError("Faltan datos del punto de venta de Costa Urbana en el diario asociado")

        # Obtener métodos de pago
        metodosPago = self.journal_id.shopping_payment_method_ids
        if not metodosPago or len(metodosPago) == 0:
            raise UserError("Debe haber al menos un método de pago configurado")
        
        pagoTotalSinIva, pagoTotalConIva = self._calcular_totales_iva()

        
        monto_contado = 0.0
        monto_credito = 0.0
        monto_debito = 0.0

        try:
            distribuido = json.loads(self.payment_distribution) if self.payment_distribution else []
        except:
            distribuido = []

        _logger.info("Distribución de pagos (CON IVA): %s", distribuido)

        if distribuido:
            total_distribuido = sum(d.get('amount', 0.0) for d in distribuido)
            _logger.info("Total distribuido (CON IVA): %s vs Total factura (CON IVA): %s", 
                        total_distribuido, pagoTotalConIva)
            
            if abs(total_distribuido - pagoTotalConIva) > 5.0:
                _logger.warning("La distribución no coincide con el total. Recalculando proporcionalmente")
                _logger.warning("Distribución suma: %s, Total factura: %s", total_distribuido, pagoTotalConIva)
                
                
                distribuido_recalculado = []
                for distribucion in distribuido:
                    if total_distribuido > 0:
                        porcentaje = distribucion.get('amount', 0.0) / total_distribuido
                        nuevo_monto = pagoTotalConIva * porcentaje
                    else:
                        nuevo_monto = 0.0
                    
                    distribuido_recalculado.append({
                        'payment_method_id': distribucion.get('payment_method_id'),
                        'amount': nuevo_monto
                    })
                    _logger.info(f"Método {distribucion.get('payment_method_id')}: {distribucion.get('amount')} → {nuevo_monto} (CON IVA)")
                
                distribuido = distribuido_recalculado
            
            # Convertir distribución CON IVA a SIN IVA proporcionalmente
            if pagoTotalConIva > 0:
                factor_sin_iva = pagoTotalSinIva / pagoTotalConIva
                
                for pago in metodosPago:
                    asignado_con_iva = 0.0
                    
                    for distribucion in distribuido:
                        if distribucion.get('payment_method_id') == pago.id:
                            asignado_con_iva = float(distribucion.get('amount', 0.0))
                            break
                    
                    asignado_sin_iva = asignado_con_iva * factor_sin_iva
                    
                    if pago.esContado():
                        monto_contado += asignado_sin_iva
                    elif pago.esCredito():
                        monto_credito += asignado_sin_iva
                    elif pago.esDebito():
                        monto_debito += asignado_sin_iva
        else:
            if len(metodosPago) == 1:
                pago = metodosPago[0]
                
                if pago.esContado():
                    monto_contado = pagoTotalSinIva
                elif pago.esCredito():
                    monto_credito = pagoTotalSinIva
                elif pago.esDebito():
                    monto_debito = pagoTotalSinIva
                
                _logger.info(f"Método único {pago.name}: {pagoTotalSinIva} (SIN IVA)")
            else:
                self.env['ventas.log'].sudo().create({
                    'account_move_id': self.id,
                    'fecha_declaracion': fields.Datetime.now(),
                    'estado': 'error',
                    'texto': f'Debe definir la distribución de pagos cuando hay múltiples métodos de pago'
                })
                raise UserError("Debe definir la distribución de pagos cuando hay múltiples métodos")

        # Datos CFE
        codigoCFE, serieCFE, numeroCFE = '', '', ''
        if self.cfe_serie_num:
            codigoCFE, serieCFE, numeroCFE = self.cfe_serie_num.split('-')

        if self.journal_id.homologacion:
            _logger.info("Modo homologación activo - Costa Urbana")
            codigoCFE = "101"
            serieCFE = "PRU"
            numeroCFE = str(random.randint(1, 1000))

        try:
            # Preparar datos de fecha/hora
            fecha_emision = self._format_fecha_emision_cfe()
            fecha_transferencia = fields.Date.today().isoformat()  # Formato: 2026-01-30
            
            # Extraer hora para el campo Horatransferencia
            if self.cfe_fecha_hora_firma:
                try:
                    dt = datetime.fromisoformat(self.cfe_fecha_hora_firma)
                    hora_transferencia = dt.strftime('%H:%M')
                except (ValueError, AttributeError):
                    hora_transferencia = self._now_uruguay().strftime('%H:%M')
            else:
                hora_transferencia = self._now_uruguay().strftime('%H:%M')

            secuencial = self.journal_id.secuencial_ventas or 1;

            # Construir diccionario de cabecera para wsDeclaVtas (Costa Urbana)
            cab_data = {
                'NumeroRUT': rut,
                'CodigoShopping': codigoShopping,
                'NumeroContrato': numeroContrato,
                'CodigoCanal': codigoCanal,
                'Secuencial': secuencial,
                'Caja': self.journal_id.caja or 1,
                'CodigoCFE': codigoCFE,
                'NumeroCFE': numeroCFE,
                'SerieCFE': serieCFE,
                'MonedaCFE': 'UYU',
                'FechaEmisionCFE': fecha_emision,
                'TotalMOCIVA': str(round(pagoTotalConIva, 2)),
                'TotalMNSIVA': str(round(pagoTotalSinIva, 2)),
                'FechaTransferencia': fecha_transferencia,
                'Horatransferencia': hora_transferencia,
                'CantidadCuotas': 1
            }
            
            # Ajustar discrepancia por redondeos si la hay
            suma_actual = monto_contado + monto_credito + monto_debito
            discrepancia = pagoTotalSinIva - suma_actual
            
            if abs(discrepancia) > 0.01:
                _logger.warning(f"Discrepancia detectada: {pagoTotalSinIva} vs {suma_actual}, diferencia: {discrepancia}")
                
                # Ajustar al mayor monto
                if monto_contado >= monto_credito and monto_contado >= monto_debito and monto_contado > 0:
                    monto_contado += discrepancia
                elif monto_credito >= monto_debito and monto_credito > 0:
                    monto_credito += discrepancia
                elif monto_debito > 0:
                    monto_debito += discrepancia
                    
                _logger.info(f"Ajuste ({discrepancia}) aplicado")
            
            request_data = {
                'wsDeclaVtas': {
                    'General': {
                        'Cab': cab_data,
                        'Det': {
                            'CodRubro': codigoRubro,
                            'ContadoMNSIVA': str(round(monto_contado, 2)),
                            'CreditoMNSIVA': str(round(monto_credito, 2)),
                            'DebitoMNSIVA': str(round(monto_debito, 2)),
                            'IncluirenPromo': self._obtener_incluir_promo()
                        }
                    }
                }
            }

            _logger.info("REQUEST COSTA URBANA (wsDeclaVtas) => %s", request_data)

            response = client.service.procesarAlta(**request_data)

            _logger.info("=== RESPUESTA RECIBIDA COSTA URBANA ===")
            _logger.info("Tipo: %s", type(response))
            response_dict = serialize_object(response)
            _logger.info("Datos: %s", response_dict)

            if isinstance(response_dict, list) and len(response_dict) > 0:
                primer_resultado = response_dict[0]
                estado = primer_resultado.get('estado')
                mensaje = primer_resultado.get('mensaje', '')
                identificador = primer_resultado.get('identificador')

                if estado == 0:
                    _logger.info("=== DECLARACIÓN EXITOSA COSTA URBANA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.write({
                        'estadoEnvio': 'enviado'
                    })
                    
                    self.journal_id.write({'secuencial_ventas': secuencial + 1})

                    self.env['ventas.log'].sudo().create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'exito',
                        'texto': f'Venta declarada correctamente en Costa Urbana. ID: {identificador}'
                    })

                    self.env.cr.commit()

                    message_id = self.env['message.wizard'].create({
                        'message': "Venta declarada correctamente en Costa Urbana. ID: %s" % identificador
                    })
                    return {
                        'name': 'Resultado Declaración Venta',
                        'type': 'ir.actions.act_window',
                        'view_mode': 'form',
                        'res_model': 'message.wizard',
                        'res_id': message_id.id,
                        'target': 'new'
                    }
                
                if estado == 1:
                    _logger.info("=== DECLARACIÓN PRE-GRABADA COSTA URBANA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.journal_id.write({'secuencial_ventas': secuencial + 1})
                    self.write({
                        'estadoEnvio': 'error'
                    })
                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'warning',
                        'texto': f'Venta pre-grabada en Costa Urbana. ID: {identificador}'
                    })

                    self.env.cr.commit()
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Éxito',
                            'message': f'Venta pre-grabada correctamente en Costa Urbana. ID: {identificador}',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
                
                if estado == 2 or estado == 3:
                    _logger.error("=== ERROR COSTA URBANA ===")
                    _logger.error(f"Estado: {estado}")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error en Costa Urbana (Estado {estado}): {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al declarar venta en Costa Urbana (Estado {estado}): {mensaje}")
                
                else:
                    _logger.error("=== DECLARACIÓN FALLIDA COSTA URBANA ===")
                    _logger.error(f"Estado: {estado}")
                    _logger.error(f"Mensaje: {mensaje}")

                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'error',
                        'texto': f'Error al declarar venta en Costa Urbana: {mensaje}'
                    })

                    self.write({
                        'estadoEnvio': 'error'
                    })

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al declarar venta en Costa Urbana: {mensaje}")
            else:
                raise UserError("Respuesta del servicio web de Costa Urbana no válida")

        except Exception as e:
            _logger.error("Error completo Costa Urbana: %s", str(e), exc_info=True)

            self.env['ventas.log'].create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': f'Error al declarar venta en Costa Urbana: {str(e)}'
            })

            self.write({
                'estadoEnvio': 'error'
            })

            self.env.cr.commit()
            raise


    
   
    
    def post_soap_xml(self, url, xml):
        rut, password = self.get_credentials();

        headers = {
            "Content-Type": "text/xml; charset=utf-8"
        }

        response = requests.post(
            url,
            data=xml.encode("utf-8"),
            headers=headers,
            auth=(rut, password),
            timeout=30
        )

        _logger.info("SOAP status %s", response.status_code)
        _logger.debug("SOAP response:\n%s", response.text)

        return response

    