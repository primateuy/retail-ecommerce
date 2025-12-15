from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión del modelo pos.order para manejar facturación sin descarga de PDF
    y asegurar que account_move esté disponible en el resultado.
    También proporciona métodos para obtener datos del CFE desde account_move
    para mostrarlos en el recibo.
    """
    _inherit = 'pos.order'

    def _generate_pos_order_invoice(self):
        """
        Genera la factura de la orden POS sin generar PDF
        
        Este método sobrescribe el método estándar para deshabilitar la generación
        de PDF durante la creación de la factura, lo cual es útil cuando se usa
        facturación electrónica que genera su propio PDF.
        
        Solo se aplica si la configuración 'download_invoice' del POS está en False.
        Si está en True, se mantiene el comportamiento estándar de Odoo.
        
        Returns:
            dict: Resultado de la generación de factura (puede ser un dict vacío
                  o un dict con información de la factura)
        """
        # Verificar si la configuración del POS permite descargar factura
        # Si download_invoice es True, usar comportamiento estándar
        if self.config_id.download_invoice:
            return super(PosOrder, self)._generate_pos_order_invoice()
        
        # Si download_invoice es False, deshabilitar generación de PDF
        ctx = dict(self.env.context)
        ctx['generate_pdf'] = False
        self = self.with_context(ctx)
        res = super(PosOrder, self)._generate_pos_order_invoice()
        return res

    @api.model
    def create_from_ui(self, orders, draft=False):
        """
        Crea órdenes desde la interfaz de usuario y asegura que account_move
        esté disponible en el resultado cuando la orden está facturada
        
        Este método sobrescribe el método estándar para asegurar que después
        de procesar las órdenes, si alguna está facturada, el campo account_move
        esté incluido en el resultado que se retorna al frontend.
        
        El problema que resuelve es que cuando se genera facturación electrónica,
        el proceso puede tomar tiempo y el campo account_move puede no estar
        disponible inmediatamente en el resultado serializado.
        
        Args:
            orders (list): Lista de órdenes a procesar
            draft (bool): Indica si las órdenes son borradores
            
        Returns:
            list: Lista de diccionarios con información de las órdenes procesadas,
                  incluyendo account_move si la orden está facturada
        """
        _logger.info(
            'create_from_ui llamado con %s órdenes, draft=%s',
            len(orders) if orders else 0,
            draft
        )
        
        # Procesar las órdenes normalmente
        result = super(PosOrder, self).create_from_ui(orders, draft)
        
        # IMPORTANTE: Siempre asegurar que account_move esté disponible en el resultado
        # cuando la orden está facturada, independientemente del valor de download_invoice.
        # Esto es necesario porque:
        # - Si download_invoice = True: el frontend necesita account_move para descargar la factura
        # - Si download_invoice = False: el frontend puede necesitar account_move para otras operaciones
        # 
        # La diferencia está solo en la generación de PDF (manejada en _generate_pos_order_invoice)
        # y en el comportamiento del frontend (manejado en payment_screen.js)
        
        # Extraer referencias de las órdenes antes de procesarlas
        order_references = []
        if orders:
            for order_data in orders:
                if isinstance(order_data, dict) and 'data' in order_data:
                    order_ref = order_data['data'].get('name') or order_data['data'].get('pos_reference')
                    if order_ref:
                        order_references.append(order_ref)
                elif isinstance(order_data, dict) and 'name' in order_data:
                    order_references.append(order_data.get('name'))
        
        _logger.info('Referencias de órdenes a procesar: %s', order_references)
        
        _logger.info(
            'create_from_ui retornó resultado tipo %s con %s elementos',
            type(result).__name__,
            len(result) if isinstance(result, (list, tuple)) else 'N/A'
        )
        
        # Si no es borrador, buscar las órdenes procesadas y agregar account_move
        # Esto se hace SIEMPRE, independientemente de download_invoice, para asegurar
        # que el frontend tenga acceso a account_move cuando la orden está facturada
        if not draft:
            # Si el resultado está vacío, buscar las órdenes por referencia
            if not result or (isinstance(result, (list, tuple)) and len(result) == 0):
                _logger.info('Resultado vacío, buscando órdenes por referencia')
                for order_ref in order_references:
                    try:
                        # Buscar la orden por referencia
                        order = self.search([('pos_reference', '=', order_ref)], limit=1)
                        if not order:
                            # Intentar buscar por name si pos_reference no funciona
                            order = self.search([('name', '=', order_ref)], limit=1)
                        
                        if order:
                            # Leer account_move directamente desde la BD
                            self.env.cr.execute(
                                "SELECT account_move FROM pos_order WHERE id = %s",
                                (order.id,)
                            )
                            account_move_result = self.env.cr.fetchone()
                            
                            if account_move_result and account_move_result[0]:
                                account_move_id = account_move_result[0]
                                
                                # Construir el resultado con account_move
                                if not result:
                                    result = []
                                result.append({
                                    'id': order.id,
                                    'account_move': account_move_id
                                })
                                _logger.info(
                                    '✓ Agregado account_move al resultado para orden %s (ID: %s): %s',
                                    order_ref,
                                    order.id,
                                    account_move_id
                                )
                            else:
                                _logger.info('Orden %s (ID: %s) no tiene account_move aún', order_ref, order.id)
                    except Exception as e:
                        _logger.warning(
                            'Error al buscar orden por referencia %s: %s',
                            order_ref,
                            str(e),
                            exc_info=True
                        )
            else:
                # Si el resultado tiene elementos, agregar account_move a cada uno
                if isinstance(result, (list, tuple)):
                    for idx, order_result in enumerate(result):
                        if isinstance(order_result, dict) and 'id' in order_result:
                            try:
                                order_id = order_result.get('id')
                                if order_id:
                                    # Leer account_move directamente desde la BD
                                    self.env.cr.execute(
                                        "SELECT account_move FROM pos_order WHERE id = %s",
                                        (order_id,)
                                    )
                                    account_move_result = self.env.cr.fetchone()
                                    
                                    if account_move_result and account_move_result[0]:
                                        account_move_id = account_move_result[0]
                                        
                                        if 'account_move' not in order_result or not order_result.get('account_move'):
                                            order_result['account_move'] = account_move_id
                                            _logger.info(
                                                '✓ Agregado account_move al resultado[%s] para orden ID %s: %s',
                                                idx,
                                                order_id,
                                                account_move_id
                                            )
                            except Exception as e:
                                _logger.warning(
                                    'Error al agregar account_move al resultado[%s]: %s',
                                    idx,
                                    str(e),
                                    exc_info=True
                                )
        
        _logger.info(
            'create_from_ui retornando resultado final: %s elementos',
            len(result) if isinstance(result, (list, tuple)) else 'N/A'
        )
        
        return result

    @api.model
    def get_cfe_data_from_invoice(self, ids, account_move_id):
        """
        Obtiene los datos del CFE directamente desde account_move (factura)
        
        Este método extrae la información del CFE desde account_move
        y la formatea para ser incluida en el recibo del POS.
        
        Args:
            ids (list): Lista de IDs de pos.order (no se usa, pero es requerido por @api.model)
            account_move_id (int): ID del account.move (factura)
        
        Returns:
            dict: Diccionario con los datos del CFE formateados para el recibo.
                  Retorna un diccionario vacío si no hay CFE disponible.
        """
        _logger.info('=== INICIO get_cfe_data_from_invoice ===')
        _logger.info('ids recibido: %s, account_move_id recibido: %s (tipo: %s)', ids, account_move_id, type(account_move_id))
        
        if not account_move_id:
            _logger.warning('No se recibió account_move_id')
            return {}
        
        cfe_data = {}
        
        try:
            # Obtener la factura (account.move)
            invoice = self.env['account.move'].browse(account_move_id)
            if not invoice.exists():
                _logger.warning('Factura %s no existe', account_move_id)
                return {}
            
            # Invalidar cache y re-leer para asegurar datos actualizados
            invoice.invalidate_recordset(['cfe_serie_num', 'name', 'cfe_hash', 'cfe_url_qr', 'cfe_type', 'qr_img', 'cfe_cae_from', 'cfe_cae_to', 'cfe_cae_exp_date', 'cfe_cae_auth'])
            invoice = invoice.browse(account_move_id)
            
            _logger.info('Factura encontrada: ID=%s, name=%s', invoice.id, invoice.name)
            
            # Parsear serie y número desde cfe_serie_num o desde el nombre de la factura
            serie = ''
            numero = ''
            tipo = ''
            
            # Intentar desde cfe_serie_num primero
            if hasattr(invoice, 'cfe_serie_num') and invoice.cfe_serie_num and str(invoice.cfe_serie_num).strip() not in [False, '/', '']:
                _logger.info('Parseando cfe_serie_num: %s', invoice.cfe_serie_num)
                parts = str(invoice.cfe_serie_num).split('-')
                if len(parts) >= 3:
                    tipo = parts[0].strip()
                    serie = parts[1].strip()
                    numero = parts[2].strip()
                    _logger.info('Parseado: tipo=%s, serie=%s, numero=%s', tipo, serie, numero)
            
            # Si no se pudo parsear desde cfe_serie_num, intentar desde el nombre
            if not serie and hasattr(invoice, 'name') and invoice.name and invoice.name.strip() not in ['/', '']:
                _logger.info('Intentando parsear desde invoice.name: %s', invoice.name)
                if '-' in invoice.name:
                    parts = invoice.name.split('-')
                    if len(parts) >= 3:
                        tipo = parts[0].strip()
                        serie = parts[1].strip()
                        numero = parts[2].strip()
                        _logger.info('Parseado desde name: tipo=%s, serie=%s, numero=%s', tipo, serie, numero)
            
            # Si no hay tipo, intentar desde cfe_type
            if not tipo and hasattr(invoice, 'cfe_type') and invoice.cfe_type:
                tipo = str(invoice.cfe_type).strip()
                _logger.info('Tipo obtenido desde cfe_type: %s', tipo)
            
            # Validar que tengamos serie y número
            if not serie or not numero:
                _logger.info('Factura %s no tiene serie y número completos (serie="%s", numero="%s")', account_move_id, serie, numero)
                return {}
            
            # Obtener el nombre del tipo de CFE
            tipo_nombre = ''
            if tipo:
                tipo_map = {
                    '101': 'eTicket',
                    '111': 'eTicket',
                    '112': 'eFactura',
                    '113': 'eFactura Exportación',
                    '181': 'eRemito',
                    '182': 'eResguardo',
                }
                tipo_nombre = tipo_map.get(tipo, f'CFE {tipo}')
            
            # Obtener RUT de la empresa
            ruc_emisor = ''
            if invoice.company_id and invoice.company_id.vat:
                ruc_emisor = invoice.company_id.vat
            
            # Obtener código de seguridad
            codigo_seguridad = ''
            if hasattr(invoice, 'cfe_hash') and invoice.cfe_hash:
                codigo_seguridad = invoice.cfe_hash
            
            # Obtener URL de verificación
            url_verificacion = ''
            if hasattr(invoice, 'cfe_url_text') and invoice.cfe_url_text:
                url_verificacion = invoice.cfe_url_text
            elif hasattr(invoice, 'cfe_url_qr') and invoice.cfe_url_qr:
                url_verificacion = invoice.cfe_url_qr
            
            # Obtener CAE
            cae_numero = ''
            if hasattr(invoice, 'cfe_cae_auth') and invoice.cfe_cae_auth:
                cae_numero = invoice.cfe_cae_auth
            
            # Obtener rangos CAE
            cae_rango_desde = ''
            cae_rango_hasta = ''
            if hasattr(invoice, 'cfe_cae_from') and invoice.cfe_cae_from:
                cae_rango_desde = str(invoice.cfe_cae_from)
            if hasattr(invoice, 'cfe_cae_to') and invoice.cfe_cae_to:
                cae_rango_hasta = str(invoice.cfe_cae_to)
            
            # Formatear fecha de vencimiento CAE
            fecha_vencimiento = ''
            if hasattr(invoice, 'cfe_cae_exp_date') and invoice.cfe_cae_exp_date:
                try:
                    if isinstance(invoice.cfe_cae_exp_date, str):
                        from datetime import datetime
                        fecha = datetime.strptime(invoice.cfe_cae_exp_date, '%Y-%m-%d')
                        fecha_vencimiento = fecha.strftime('%d/%m/%Y')
                    else:
                        fecha_vencimiento = invoice.cfe_cae_exp_date.strftime('%d/%m/%Y')
                except Exception:
                    fecha_vencimiento = str(invoice.cfe_cae_exp_date)
            
            # Obtener QR en base64
            qr_base64 = ''
            if hasattr(invoice, 'qr_img') and invoice.qr_img:
                qr_base64 = invoice.qr_img
            
            # Construir objeto con datos del CFE
            cfe_data = {
                'tipo': tipo_nombre,
                'serie': serie,
                'numero': numero,
                'ruc_emisor': ruc_emisor,
                'codigo_seguridad': codigo_seguridad,
                'url_verificacion': url_verificacion,
                'cae_numero': cae_numero,
                'cae_rango_desde': cae_rango_desde,
                'cae_rango_hasta': cae_rango_hasta,
                'cae_fecha_vencimiento': fecha_vencimiento,
                'qr_base64': qr_base64,
            }
            
            _logger.info('✓ Datos CFE obtenidos desde factura %s: tipo=%s, serie=%s, numero=%s', account_move_id, tipo_nombre, serie, numero)
            
        except Exception as e:
            _logger.error('Error al obtener datos CFE desde factura %s: %s', account_move_id, str(e), exc_info=True)
            return {}
        
        return cfe_data
