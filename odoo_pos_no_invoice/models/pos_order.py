from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión del modelo pos.order para manejar facturación sin descarga de PDF
    y asegurar que account_move esté disponible en el resultado
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
                                # Construir el resultado con account_move
                                if not result:
                                    result = []
                                result.append({
                                    'id': order.id,
                                    'account_move': account_move_result[0]
                                })
                                _logger.info(
                                    '✓ Agregado account_move al resultado para orden %s (ID: %s): %s',
                                    order_ref,
                                    order.id,
                                    account_move_result[0]
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
                                        if 'account_move' not in order_result or not order_result.get('account_move'):
                                            order_result['account_move'] = account_move_result[0]
                                            _logger.info(
                                                '✓ Agregado account_move al resultado[%s] para orden ID %s: %s',
                                                idx,
                                                order_id,
                                                account_move_result[0]
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
