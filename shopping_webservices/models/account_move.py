import random

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
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    payment_distribution = fields.Text(
        string='Distribución de Pagos',
        help='JSON con la distribución de pagos por método'
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
    
    @api.depends('journal_id', 'journal_id.tecnologia', 'journal_id.shopping_payment_method_ids')
    def _compute_mostrar_botones_declaracion(self):
        for record in self:
            record.mostrar_botones_declaracion = (
                record.journal_id.tecnologia and 
                record.journal_id.shopping_payment_method_ids
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

    ventaEnviada = fields.Boolean(
        string="Venta Enviada al Shopping", 
        default=False,
        readonly=True,  # Solo se actualiza programáticamente
        copy=False  # No se copia al duplicar
    )
    metodoUnico = fields.Boolean(string="Método Único", default=True, compute="_computar_tipo_venta", store=True);

    logs = fields.One2many(
        'ventas.log',
        'account_move_id',
        string="Logs de Ventas Declaradas"
    )

    x_widget_dummy = fields.Char(string="Widget Dummy", compute='_compute_widget_dummy', store=False)
    
    def _compute_widget_dummy(self):
        for record in self:
            record.x_widget_dummy = ''

    @api.depends('journal_id.shopping_payment_method_ids')
    def _computar_tipo_venta(self):
        journal = self.journal_id;

        if journal.shopping_payment_method_ids and len(journal.shopping_payment_method_ids) == 1:
            self.metodoUnico = True;
        else:
            self.metodoUnico = False;

    def get_credentials(self):
        rut = self.env['ir.config_parameter'].sudo().get_param('shopping_webservices.rut')
        password = self.env['ir.config_parameter'].sudo().get_param('shopping_webservices.password')


        _logger.info("Credenciales obtenidas: RUT=%s", rut);
        _logger.info("CREDENCIALES OBTENIDAS: PASSWORD=%s", password);

        if not rut or not password:
            raise ValueError("Faltan credenciales del shopping")

        return str(rut), str(password)

    
    def get_zeep_client(self, wsdl_url):
        rut, password = self.get_credentials()

        session = Session()
        session.verify = True
        session.auth = HTTPBasicAuth(rut, password)

        transport = Transport(session=session, timeout=20)

        _logger.info("Creando cliente Zeep para %s", wsdl_url)
        client = Client(wsdl=wsdl_url, transport=transport)

        if client is None:
            raise ValueError("No se pudo crear el cliente Zeep")

        return client;

    def declararVentaVariosMetodos(self):
        tipo = self.env['account.journal'].browse(self.journal_id.id).tecnologia;

        if not tipo or tipo == '':
            _logger.info("No se encontro tipo !!");
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'Falta definir la tecnología del punto de venta en el diario asociado.'
            })

        if tipo == 'lecueder':
            self.declararVentaVariosMetodosLecueder();
        elif tipo == 'costa_urbana':

            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'No implementado para Costa Urbana aún.'
            })
            _logger.info("No implementado para Costa Urbana aún");
            pass;
    
    
        


    def declararVentaUnicoMetodo(self):
        tipo = self.env['account.journal'].browse(self.journal_id.id).tecnologia;

        if not tipo or tipo == '':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'Falta definir la tecnología del punto de venta en el diario asociado.'
            })
            return;
    

        if tipo == 'costa_urbana':
            self.env['ventas.log'].sudo().create({
                'account_move_id': self.id,
                'fecha_declaracion': fields.Datetime.now(),
                'estado': 'error',
                'texto': 'No implementado para Costa Urbana aún.'
            })

            return;
    

        url = self.env['ir.config_parameter'].sudo().get_param('shopping_webservices.url_declaracion_ventas')
        
        client = self.get_zeep_client(url)
        _logger.info("Cliente Zeep creado exitosamente")

        if not url:
            raise UserError("Falta URL de declaración de ventas en la configuración")

        rut = self.env['ir.config_parameter'].sudo().get_param('shopping_webservices.rut')

        if not rut:
            raise UserError("Falta RUT en la configuración")

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

        for linea in lineas:
            _logger.info("Línea: %s - Cantidad: %s - Precio Unitario: %s", linea.name, linea.quantity, linea.price_unit)
            
            subtotal = linea.quantity * linea.price_unit
            
            # Calcular impuestos
            if linea.tax_ids:
                tasa_impuesto = sum(tax.amount for tax in linea.tax_ids)
                subtotal_con_iva = subtotal * (1 + (tasa_impuesto / 100.0))
            else:
                subtotal_con_iva = subtotal
            
            _logger.info("Subtotal sin IVA: %s - Subtotal con IVA: %s", subtotal, subtotal_con_iva)

            pagoTotalSinIva += subtotal
            pagoTotalConIva += subtotal_con_iva

        _logger.info("=== TOTALES CALCULADOS ===")
        _logger.info("Total sin IVA: %s", pagoTotalSinIva)
        _logger.info("Total con IVA: %s", pagoTotalConIva)

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
                            'NumeroCFE': numeroCFE,  # Usar el número de factura
                            'SerieCFE': serieCFE,
                            'MonedaCFE': 'UYU',
                            'FechaEmisionCFE': fields.Date.today().strftime('%Y-%m-%d'),
                            'TotalMOCIVA': str(pagoTotalConIva),  # ← CORREGIDO: Usar calculado
                            'TotalMNSIVA': str(pagoTotalSinIva),  # ← CORREGIDO: Usar calculado
                            'TipodeCambio': '1'
                        },
                        'Det': {
                            'CodRubro': codigoRubro,
                            'ContadoMNSIVA': monto_contado,    # ← CORREGIDO: Usar calculado
                            'CreditoMNSIVA': monto_credito,    # ← CORREGIDO: Usar calculado
                            'DebitoMNSIVA': monto_debito,      # ← CORREGIDO: Usar calculado
                            'IncluirenPromo': 'S'
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
                    
                    # Guardar que la venta fue enviada
                    self.write({'ventaEnviada': True})
                    

                    self.env['ventas.log'].sudo().create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'exito',
                        'texto': f'Venta declarada correctamente. ID: {identificador}'
                    })

                    self.env.cr.commit();

                    message_id = self.env['message.wizard'].create({'message': "Venta declarada correctamente. ID: %s" % identificador})
                    return {
                        'name': 'Resultado Declaración Venta',
                        'type': 'ir.actions.act_window',
                        'view_mode': 'form',
                        'res_model': 'message.wizard',
                        # pass the id
                        'res_id': message_id.id,
                        'target': 'new'
                    }

                    
                
                if estado == 1:
                    _logger.info("=== DECLARACIÓN EXITOSA ===")
                    _logger.info(f"Identificador: {identificador}")
                    
                    self.env['ventas.log'].create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'warning',
                        'texto': f'Venta pre-grabada. ID: {identificador}'
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

                    self.env.cr.commit();
                    
                    raise UserError(f"Error al declarar la venta (Estado {estado}): {mensaje}")
            else:
                raise UserError("Respuesta del servicio web no válida")

        except Exception as e:
            _logger.error("Error completo: %s", str(e), exc_info=True)
            raise

    def declararVentaVariosMetodosLecueder(self):
        """
        Declara una venta con múltiples métodos de pago (crédito, débito, contado)
        Distribuye el monto según el JSON de payment_distribution (que incluye IVA) 
        pero convierte a SIN IVA para el envío al servicio
        """
        url = self.env['ir.config_parameter'].sudo().get_param('shopping_webservices.url_declaracion_ventas')
        
        client = self.get_zeep_client(url)
        _logger.info("Cliente Zeep creado exitosamente para múltiples métodos")

        if not url:
            raise UserError("Falta URL de declaración de ventas en la configuración")

        rut = self.env['ir.config_parameter'].sudo().get_param('shopping_webservices.rut')

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

        for linea in self.invoice_line_ids:
            _logger.info("Línea: %s - Cantidad: %s - Precio Unitario: %s", linea.name, linea.quantity, linea.price_unit)
            
            subtotal = linea.quantity * linea.price_unit
            
            # Calcular impuestos
            if linea.tax_ids:
                tasa_impuesto = sum(tax.amount for tax in linea.tax_ids)
                subtotal_con_iva = subtotal * (1 + (tasa_impuesto / 100.0))
            else:
                subtotal_con_iva = subtotal
            
            _logger.info("Subtotal sin IVA: %s - Subtotal con IVA: %s", subtotal, subtotal_con_iva)

            pagoTotalSinIva += subtotal
            pagoTotalConIva += subtotal_con_iva

        _logger.info("=== TOTALES CALCULADOS ===")
        _logger.info("Total sin IVA: %s", pagoTotalSinIva)
        _logger.info("Total con IVA: %s", pagoTotalConIva)

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
                            'FechaEmisionCFE': fields.Date.today().strftime('%Y-%m-%d'),
                            'TotalMOCIVA': str(pagoTotalConIva),
                            'TotalMNSIVA': str(pagoTotalSinIva),
                            'TipodeCambio': '1'
                        },
                        'Det': {
                            'CodRubro': codigoRubro,
                            'ContadoMNSIVA': str(round(monto_contado, 2)),
                            'CreditoMNSIVA': str(round(monto_credito, 2)),
                            'DebitoMNSIVA': str(round(monto_debito, 2)),
                            'IncluirenPromo': 'S'
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
                    self.write({'ventaEnviada': True})
                    
                    self.env['ventas.log'].sudo().create({
                        'account_move_id': self.id,
                        'fecha_declaracion': fields.Datetime.now(),
                        'estado': 'exito',
                        'texto': f'Venta declarada correctamente. ID: {identificador}'
                    })

                    self.env.cr.commit()

                    message_id = self.env['message.wizard'].create({'message': "Venta declarada correctamente. ID: %s" % identificador})
                    return {
                        'name': 'Resultado Declaración Venta',
                        'type': 'ir.actions.act_window',
                        'view_mode': 'form',
                        'res_model': 'message.wizard',
                        'res_id': message_id.id,
                        'target': 'new'
                    }
                
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

                    self.env.cr.commit()
                    
                    raise UserError(f"Error al declarar la venta (Estado {estado}): {mensaje}")
            else:
                raise UserError("Respuesta del servicio web no válida")

        except Exception as e:
            _logger.error("Error completo: %s", str(e), exc_info=True)
            raise

    def llamadoPruebaZeep3(self):
        # Declarar ventas
        url = 'https://portal.trescruces.com.uy/soap/portal/services/forms/v1.3/wsDeclaVtas?wsdl'

        client = self.get_zeep_client(url)

        try:
            request_data = {
                'wsDeclaVtas': {
                    'General': {
                        'Cab': {
                            'NumeroRUT': '212062150010',
                            'CodigoShopping': 'TCS',
                            'NumeroContrato': '959',
                            'CodigoCanal': '1',
                            'CodigoCFE': '101',
                            'NumeroCFE': '231',
                            'SerieCFE': 'A',
                            'MonedaCFE': 'UYU',
                            'FechaEmisionCFE': '2025-12-12 15:30',
                            'TotalMOCIVA': '1220.00',
                            'TotalMNSIVA': '1000.00',
                            'TipodeCambio': '1'
                        },
                        'Det': {
                            'CodRubro': 'TCS43',
                            'ContadoMNSIVA': '1000',
                            'CreditoMNSIVA': '0',
                            'DebitoMNSIVA': '0',
                            'IncluirenPromo': 'S'
                        }
                    }
                }
            }

            _logger.info("Preparando para enviar request: %s", request_data)

            response = client.service.procesarAlta(**request_data)

            _logger.info("=== RESPUESTA EXITOSA ===")
            _logger.info("Tipo: %s", type(response))
            response_dict = serialize_object(response)
            _logger.info("Datos: %s", response_dict)

        except Exception as e:
            _logger.error("Error completo: %s", str(e), exc_info=True)
            raise

    def llamadoPruebaZeep2(self):
        url = 'https://portal.trescruces.com.uy/soap/portal/services/sim/v1.3/wsConsxCont?wsdl'
        client = self.get_zeep_client(url)
        
        try:
            # Opción 1: Diccionario anidado (más simple)
            request_data = {
                'wsConsxCont': {
                    'General': {
                        'Cab': {
                            'NumeroRUT': '212062150010',
                            'CodigoShopping': 'TCS',
                            'NumeroContrato': '959'
                        }
                    }
                }
            }
            
            _logger.info("Enviando request: %s", request_data)
            
            response = client.service.simular(**request_data)
            
            _logger.info("=== RESPUESTA EXITOSA ===")
            _logger.info("Tipo: %s", type(response))
            
            
            response_dict = serialize_object(response)
            _logger.info("Datos: %s", response_dict)
            
            return response_dict
            
        except Exception as e:
            _logger.error("Error completo: %s", str(e), exc_info=True)
            
            
            try:
                operation = client.service._binding._operations['simular']
                _logger.info("Firma esperada: %s", operation.input.signature())
            except:
                pass
                
            raise

    def llamadoPruebaZeep(self):
        url = 'https://portal.trescruces.com.uy/soap/portal/services/sim/v1.3/wsConsxRUT?wsdl'
        client = self.get_zeep_client(url)
        
        try:
            # Opción 1: Diccionario anidado (más simple)
            request_data = {
                'wsConsxRUT': {
                    'General': {
                        'Cab': {
                            'NumeroRUT': '212062150010'
                        }
                    }
                }
            }
            
            _logger.info("Enviando request: %s", request_data)
            
            response = client.service.simular(**request_data)
            
            _logger.info("=== RESPUESTA EXITOSA ===")
            _logger.info("Tipo: %s", type(response))
            
            
            response_dict = serialize_object(response)
            _logger.info("Datos: %s", response_dict)
            
            return response_dict
            
        except Exception as e:
            _logger.error("Error completo: %s", str(e), exc_info=True)
            
            # Mostrar la firma esperada
            try:
                operation = client.service._binding._operations['simular']
                _logger.info("Firma esperada: %s", operation.input.signature())
            except:
                pass
                
            raise

    def llamadoPruebaXML(self):
        url = 'https://portal.trescruces.com.uy/soap/portal/services/sim/v1.3/wsConsxRUT';


        xml = """<soapenv:Envelope
            xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
            xmlns:sim="http://nodum.com.uy/soap/portal/schemas/sim/v1.3/wsConsxRUT">

            <soapenv:Header/>

            <soapenv:Body>
                <sim:simular>
                    <sim:wsConsxRUT>
                        <sim:General>
                            <sim:Cab>
                                <sim:NumeroRUT>212062150010</sim:NumeroRUT>
                            </sim:Cab>
                        </sim:General>
                    </sim:wsConsxRUT>
                </sim:simular>
            </soapenv:Body>

        </soapenv:Envelope>
        """

        response = self.post_soap_xml(url, xml);
    
        _logger.info("Respuesta SOAP recibida: %s", response.text);

    
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