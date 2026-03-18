# -*- coding: utf-8 -*-
"""
Extensión del modelo pos.order para soporte de promociones OCA

Este módulo agrega funcionalidad para:
- Agregar líneas de descuento por promociones
- Obtener totales actualizados de órdenes
"""

import logging

from odoo import models, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión del modelo pos.order para promociones OCA
    """
    _inherit = 'pos.order'

    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para agregar línea de descuento de promoción
        cuando se crea la orden, si hay una transacción OCA asociada con promoción
        """
        # Crear la orden primero
        order = super(PosOrder, self).create(vals)
        
        # Buscar transacciones OCA asociadas con promoción en esta sesión
        try:
            session_id = order.session_id.id if order.session_id else False
            if session_id:
                # Buscar transacciones OCA con promoción que no tengan orden asociada
                # IMPORTANTE: Filtrar por sesión POS si es posible, y ordenar por fecha de creación descendente
                # para tomar la más reciente. En promociones, el monto de la transacción ($1290) 
                # NO coincide con el monto del pago ($1720) porque el descuento se aplica en el POS
                search_domain = [
                    ('oca_transaction_id', '!=', False),
                    ('is_promotion', '=', True),
                    ('pos_order_id', '=', False),
                    ('state', 'in', ['pending', 'done'])
                ]
                
                # Intentar filtrar por sesión si hay un campo de sesión en payment.transaction
                # Por ahora, buscar todas las transacciones con promoción y luego filtrar por fecha
                oca_transactions = self.env['payment.transaction'].sudo().search(
                    search_domain, 
                    order='create_date desc, id desc',
                    limit=10  # Limitar a las 10 más recientes para mejorar rendimiento
                )
                
                # Si hay pagos OCA en esta orden, intentar buscar por TransactionId primero
                oca_payments = order.payment_ids.filtered(
                    lambda p: p.payment_method_id.use_payment_terminal == 'oca'
                )
                
                oca_transaction = None
                if oca_payments:
                    # Primero intentar buscar por TransactionId si está disponible en el pago
                    for payment in oca_payments:
                        # Si el pago tiene una transacción asociada, usarla
                        if payment.payment_transaction_id and payment.payment_transaction_id.is_promotion:
                            oca_transaction = payment.payment_transaction_id
                            _logger.info('Transacción OCA encontrada por payment_transaction_id: %s (Monto: %s)', 
                                       oca_transaction.oca_transaction_id, oca_transaction.amount)
                            break
                    
                    # Si no se encontró por payment_transaction_id, buscar por monto
                    # PERO en promociones, el monto puede no coincidir, así que también considerar
                    # transacciones recientes con promoción
                    if not oca_transaction:
                        for payment in oca_payments:
                            for trans in oca_transactions:
                                # Coincidencia exacta de monto (puede no funcionar en promociones)
                                if abs(trans.amount - payment.amount) < 0.01:
                                    oca_transaction = trans
                                    _logger.info('Transacción OCA encontrada por monto: %s (Monto: %s)', 
                                               trans.oca_transaction_id, trans.amount)
                                    break
                            if oca_transaction:
                                break
                
                # Si no se encontró por monto o payment_transaction_id, tomar la más reciente con promoción
                # Esto es importante porque en promociones el monto no coincide
                if not oca_transaction and oca_transactions:
                    # Filtrar transacciones creadas en los últimos 5 minutos para esta sesión
                    from datetime import datetime, timedelta
                    five_minutes_ago = datetime.now() - timedelta(minutes=5)
                    recent_transactions = oca_transactions.filtered(
                        lambda t: t.create_date and t.create_date >= five_minutes_ago
                    )
                    if recent_transactions:
                        oca_transaction = recent_transactions[0]
                        _logger.info('Usando transacción OCA más reciente con promoción (últimos 5 min): %s (Monto: %s, Pago: %s)', 
                                   oca_transaction.oca_transaction_id, oca_transaction.amount, 
                                   oca_payments[0].amount if oca_payments else 'N/A')
                    else:
                        # Si no hay transacciones recientes, usar la más reciente de todas formas
                        oca_transaction = oca_transactions[0]
                        _logger.info('Usando transacción OCA más reciente con promoción: %s (Monto: %s)', 
                                   oca_transaction.oca_transaction_id, oca_transaction.amount)
                
                if oca_transaction:
                    # Obtener información de promoción de la transacción
                    import json
                    try:
                        complete_response = json.loads(oca_transaction.oca_complete_response or '{}')
                        promotion_info = complete_response.get('promotion_info', {})

                        # Normalizar promotion_info para asegurar que sea un dict
                        # En algunos escenarios puede haberse almacenado como string JSON.
                        if isinstance(promotion_info, str):
                            try:
                                promotion_info = json.loads(promotion_info) or {}
                            except Exception as norm_error:
                                _logger.error(
                                    'promotion_info almacenado como string no JSON para transacción %s: %s',
                                    oca_transaction.oca_transaction_id, str(norm_error)
                                )
                                promotion_info = {}
                        
                        # Verificar que la promoción esté activa y tenga información válida
                        if promotion_info and promotion_info.get('is_promotion'):
                            discount_amount = promotion_info.get('discount_amount', 0)
                            product_id = promotion_info.get('product_id', False)
                            description = promotion_info.get('description', 'Descuento Promoción')
                            promotion_id = promotion_info.get('promotion_id', False)
                            
                            if discount_amount > 0 and product_id:
                                # Verificar incompatibilidades antes de agregar la línea de descuento
                                should_apply = True
                                if promotion_id:
                                    promotion = self.env['payment.method.promotion'].browse(promotion_id)
                                    if promotion.exists():
                                        # Verificar si hay promociones incompatibles ya aplicadas
                                        is_incompatible, incompatible_promotions, incompat_msg = promotion._check_incompatibilities(order)
                                        if is_incompatible:
                                            _logger.warning('No se puede aplicar promoción %s (ID: %s) porque es incompatible con: %s. %s', 
                                                          promotion.name, promotion.id, 
                                                          ', '.join([p.name for p in incompatible_promotions]),
                                                          incompat_msg)
                                            # No agregar la línea de descuento
                                            should_apply = False
                                
                                if should_apply:
                                    # Agregar línea de descuento a la orden
                                    discount_result = order.add_promotion_discount_line(
                                        discount_amount,
                                        product_id,
                                        description,
                                        promotion_id=promotion_id
                                    )
                                    
                                    if discount_result.get('success'):
                                        # Asociar la transacción con la orden
                                        oca_transaction.pos_order_id = order.id
                                        # También asociar con el pago si hay uno
                                        if oca_payments and oca_payments[0]:
                                            oca_transaction.pos_payment_id = oca_payments[0].id
                                            # Actualizar el payment_transaction_id en el pago
                                            oca_payments[0].payment_transaction_id = oca_transaction.id
                                        _logger.info('Línea de descuento de promoción agregada a orden %s desde transacción OCA %s (Descuento: %s)', 
                                                   order.name, oca_transaction.oca_transaction_id, discount_amount)
                                    else:
                                        _logger.error('Error al agregar línea de descuento: %s', discount_result.get('error'))
                            else:
                                _logger.warning('Información de promoción incompleta: discount_amount=%s, product_id=%s', 
                                              discount_amount, product_id)
                        else:
                            _logger.warning('Transacción OCA %s no tiene información de promoción válida', 
                                          oca_transaction.oca_transaction_id)
                    except Exception as e:
                        _logger.error('Error al procesar información de promoción de transacción: %s', str(e))
                        import traceback
                        _logger.error('Traceback: %s', traceback.format_exc())
        except Exception as e:
            _logger.error('Error al agregar línea de descuento al crear orden: %s', str(e))
        
        return order

    def add_promotion_discount_line(self, discount_amount, product_id, description, promotion_id=False):
        """
        Agrega una línea de descuento por promoción a la orden POS
        
        Este método se utiliza cuando se detecta una promoción aplicable.
        
        Args:
            discount_amount (float): Monto del descuento
            product_id (int): ID del producto de descuento
            description (str): Descripción del descuento
            promotion_id (int, optional): ID de la promoción aplicada (para rastreo de incompatibilidades)
        basada en datos de la tarjeta (Acquirer/Issuer).
        
        Args:
            discount_amount (float): Monto del descuento (positivo, se convertirá a negativo)
            product_id (int): ID del producto de descuento
            description (str): Descripción del descuento
            
        Returns:
            dict: Resultado de la operación con keys:
                - success: bool - Si se agregó correctamente
                - error: str - Mensaje de error si falló
                - line_id: int - ID de la línea creada si fue exitoso
        """
        self.ensure_one()
        
        try:
            # Validar que el producto existe
            product = self.env['product.product'].browse(product_id)
            if not product.exists():
                _logger.error('Producto de descuento no encontrado: %s', product_id)
                return {
                    'success': False,
                    'error': f'Producto de descuento no encontrado: {product_id}'
                }
            
            # Validar que el monto es positivo
            if discount_amount <= 0:
                _logger.error('Monto de descuento debe ser positivo: %s', discount_amount)
                return {
                    'success': False,
                    'error': f'Monto de descuento inválido: {discount_amount}'
                }
            
            # Permitir agregar descuento incluso si la orden está facturada
            # Si está facturada, también agregaremos el descuento a la factura
            if self.state not in ['draft', 'paid', 'invoiced', 'done']:
                _logger.error('No se puede agregar descuento a orden en estado: %s', self.state)
                return {
                    'success': False,
                    'error': f'Orden en estado inválido: {self.state}'
                }
            
            # Verificar si ya existe una línea de descuento de promoción para esta orden
            # (opcional: evitar duplicados)
            existing_discount_line = self.lines.filtered(
                lambda l: l.product_id.id == product_id and l.price_unit < 0
            )
            
            if existing_discount_line:
                _logger.warning('Ya existe línea de descuento de promoción en la orden. Actualizando...')
                # Actualizar la línea existente
                price_unit = -abs(discount_amount)  # Negativo para descuento
                qty = 1.0
                # Calcular price_subtotal explícitamente
                price_subtotal = price_unit * qty
                price_subtotal_incl = price_subtotal  # Sin impuestos, son iguales
                
                existing_discount_line[0].write({
                    'price_unit': price_unit,
                    'price_subtotal': price_subtotal,  # Establecer explícitamente
                    'price_subtotal_incl': price_subtotal_incl,  # También establecer price_subtotal_incl
                    'name': description or f'Descuento Promoción - {product.name}',
                    'qty': qty,
                    'discount': 0.0,  # Sin descuento adicional
                })
                # Forzar recálculo de campos calculados
                try:
                    existing_discount_line[0]._compute_amount_line_all()
                except AttributeError:
                    # Si el método no existe, forzar recálculo de otra forma
                    existing_discount_line[0]._compute_amount()
                except Exception as e:
                    _logger.warning('No se pudo recalcular campos calculados de línea de descuento existente: %s', str(e))
                line_id = existing_discount_line[0].id
            else:
                # Crear nueva línea de descuento
                # El descuento debe tener los mismos impuestos que las líneas a las que se aplica
                # para que el CFE calcule correctamente el MntNetoIVATasaBasica
                tax_ids = []
                for line in self.lines:
                    if line.product_id.id != product_id and line.tax_ids:  # Excluir la línea de descuento si ya existe
                        # Obtener todos los impuestos de la línea (no solo tasa básica)
                        # porque el descuento debe reducir el monto neto con los mismos impuestos
                        for tax in line.tax_ids:
                            if tax.id not in tax_ids:
                                tax_ids.append(tax.id)
                
                # Si no se encontraron impuestos, usar los del producto de descuento si los tiene
                if not tax_ids and product.taxes_id:
                    tax_ids = product.taxes_id.ids
                
                # Si aún no hay impuestos, buscar el impuesto a tasa básica por defecto (22%)
                if not tax_ids:
                    basic_tax = self.env['account.tax'].search([
                        ('amount', '=', 22.0),
                        ('type_tax_use', '=', 'sale'),
                        ('company_id', '=', self.company_id.id)
                    ], limit=1)
                    if basic_tax:
                        tax_ids = [basic_tax.id]
                
                # Calcular el price_unit correcto según si hay impuestos
                # IMPORTANTE: El descuento_amount que se recibe es el descuento sobre el total (con impuestos incluidos)
                # 
                # Para CFE, el método precio_unitario_cfe() usa precio_unitario(), que:
                # - Si el IVA está incluido: divide price_unit por (1 + tasa) para obtener el neto
                # - Si el IVA NO está incluido: usa price_unit directamente
                #
                # Como el descuento_amount es sobre el total (con impuestos), necesitamos:
                # - Si el IVA está incluido: usar discount_amount como price_unit (precio_unitario() lo ajustará)
                # - Si el IVA NO está incluido: calcular el descuento neto dividiendo por (1 + tasa)
                qty = 1.0
                if tax_ids:
                    taxes = self.env['account.tax'].browse(tax_ids)
                    # Verificar si los impuestos están incluidos en el precio
                    # En POS, generalmente los impuestos NO están incluidos, pero verificamos para estar seguros
                    price_include = any(tax.price_include for tax in taxes)
                    
                    if price_include:
                        # Impuestos incluidos: usar el descuento total como price_unit
                        # precio_unitario() lo dividirá por (1 + tasa) para obtener el neto correcto
                        # Esto asegura que precio_unitario_cfe() muestre el descuento neto correcto
                        price_unit = -abs(discount_amount)  # Negativo para descuento
                        _logger.info('Descuento con impuestos incluidos: price_unit=%s (descuento total), precio_unitario() calculará el neto', price_unit)
                    else:
                        # Impuestos NO incluidos: calcular el descuento neto
                        # El descuento_amount es sobre el total (con impuestos), necesitamos el neto
                        total_tax_rate = sum(tax.amount for tax in taxes) / 100.0
                        discount_net = discount_amount / (1.0 + total_tax_rate)
                        price_unit = -abs(discount_net)  # Negativo para descuento
                        _logger.info('Descuento con impuestos NO incluidos: discount_amount=%s, discount_net=%s, price_unit=%s', 
                                   discount_amount, discount_net, price_unit)
                else:
                    # Sin impuestos, el price_unit es directamente el descuento
                    price_unit = -abs(discount_amount)  # Negativo para descuento
                    _logger.info('Descuento sin impuestos: price_unit=%s', price_unit)
                
                # Crear la línea usando new() primero para que Odoo calcule los campos automáticamente
                # Esto es necesario porque en esta base de datos price_subtotal tiene NOT NULL a nivel SQL.
                discount_line_new = self.env['pos.order.line'].new({
                    'order_id': self.id,
                    'product_id': product_id,
                    'qty': qty,
                    'price_unit': price_unit,
                    'name': description or f'Descuento Promoción - {product.name}',
                    'tax_ids': [(6, 0, tax_ids)] if tax_ids else [(5, 0, 0)],
                    'full_product_name': description or f'Descuento Promoción - {product.name}',
                    'discount': 0.0,
                })

                # Forzar cálculo de campos calculados antes de crear
                try:
                    discount_line_new._onchange_qty()
                except AttributeError:
                    pass

                # Asegurar que price_subtotal y price_subtotal_incl tengan valores
                calculated_price_subtotal = price_unit * qty

                if not discount_line_new.price_subtotal:
                    discount_line_new.price_subtotal = calculated_price_subtotal

                if not discount_line_new.price_subtotal_incl:
                    if tax_ids:
                        taxes = self.env['account.tax'].browse(tax_ids)
                        total_tax_rate = sum(tax.amount for tax in taxes) / 100.0
                        discount_line_new.price_subtotal_incl = calculated_price_subtotal * (1.0 + total_tax_rate)
                    else:
                        discount_line_new.price_subtotal_incl = calculated_price_subtotal

                # Convertir a diccionario para create()
                discount_line_vals = discount_line_new._convert_to_write(discount_line_new._cache)

                # Reforzar que nunca vayan NULL a la base
                if discount_line_vals.get('price_subtotal') is None:
                    discount_line_vals['price_subtotal'] = calculated_price_subtotal
                if discount_line_vals.get('price_subtotal_incl') is None:
                    discount_line_vals['price_subtotal_incl'] = calculated_price_subtotal

                discount_line = self.env['pos.order.line'].create(discount_line_vals)
                line_id = discount_line.id
            
            # Recalcular totales de la orden
            # Odoo debería hacerlo automáticamente cuando se crean/modifican líneas
            # No es necesario llamar a ningún método explícitamente
            
            # Nota: La transformación de cantidad y monto para CFE se maneja en otro módulo
            # No es necesario agregar manualmente la línea de descuento a la factura aquí
            
            # Hacer flush para asegurar que los cambios se reflejen en la base de datos
            # sin hacer commit (el commit lo maneja el contexto de transacción)
            self.env.cr.flush()
            
            # Log detallado del descuento calculado para verificación
            discount_line = self.env['pos.order.line'].browse(line_id)
            _logger.info('Línea de descuento agregada exitosamente a orden %s: Línea ID %s', 
                        self.name, line_id)
            _logger.info('  Descuento recibido (total con impuestos): %s', discount_amount)
            _logger.info('  price_unit establecido: %s', discount_line.price_unit)
            _logger.info('  price_subtotal: %s', discount_line.price_subtotal)
            _logger.info('  price_subtotal_incl: %s', discount_line.price_subtotal_incl)
            if discount_line.tax_ids:
                _logger.info('  Impuestos aplicados: %s', ', '.join([tax.name for tax in discount_line.tax_ids]))
                _logger.info('  Impuestos incluidos en precio: %s', any(tax.price_include for tax in discount_line.tax_ids))
            
            return {
                'success': True,
                'error': None,
                'line_id': line_id
            }
            
        except Exception as e:
            # Log detallado del error para poder identificar el origen exacto
            _logger.error('Error al agregar línea de descuento a orden %s: %s', self.name, str(e))
            try:
                import traceback
                _logger.error('Traceback al agregar línea de descuento: %s', traceback.format_exc())
            except Exception:
                # Si por algún motivo falla el log de traceback, no interrumpir el flujo
                pass
            return {
                'success': False,
                'error': str(e)
            }

    def get_order_totals(self):
        """
        Obtiene los totales actualizados de la orden
        
        Returns:
            dict: Totales con keys:
                - newTotal: float - Total con impuestos
                - newTaxableAmount: float - Total sin impuestos
                - newInvoiceAmount: float - Total de factura (igual a newTotal)
        """
        self.ensure_one()
        
        try:
            # Los totales se calculan automáticamente en Odoo
            # No es necesario llamar a ningún método explícitamente
            
            return {
                'newTotal': self.amount_total,
                'newTaxableAmount': self.amount_untaxed,
                'newInvoiceAmount': self.amount_total
            }
        except Exception as e:
            _logger.error('Error al obtener totales de orden %s: %s', self.name, str(e))
            # Retornar valores actuales como fallback
            return {
                'newTotal': self.amount_total,
                'newTaxableAmount': self.amount_untaxed,
                'newInvoiceAmount': self.amount_total
            }
    
    def _generate_pos_order_invoice(self):
        """
        Sobrescribe el método para asegurar que el descuento de promoción
        se agregue ANTES de generar la factura, para que CFE reciba el monto correcto
        
        Este método se llama cuando se genera la factura de la orden POS.
        Interceptamos aquí para agregar el descuento antes de que se cree la factura.
        """
        # Buscar transacciones OCA con promoción asociadas a esta orden
        # que aún no tengan el descuento aplicado
        try:
            # Buscar pagos OCA en esta orden
            oca_payments = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'oca'
            )
            
            if oca_payments:
                # Buscar transacciones OCA con promoción asociadas a estos pagos
                for payment in oca_payments:
                    if payment.payment_transaction_id and payment.payment_transaction_id.is_promotion:
                        transaction = payment.payment_transaction_id
                        
                        # Verificar si ya tiene el descuento aplicado
                        import json
                        try:
                            complete_response = json.loads(transaction.oca_complete_response or '{}')
                            promotion_info = complete_response.get('promotion_info', {})

                            # Normalizar promotion_info para asegurar que sea un dict
                            if isinstance(promotion_info, str):
                                try:
                                    promotion_info = json.loads(promotion_info) or {}
                                except Exception as norm_error:
                                    _logger.error(
                                        'promotion_info almacenado como string no JSON para transacción %s: %s',
                                        transaction.oca_transaction_id, str(norm_error)
                                    )
                                    promotion_info = {}
                            
                            if promotion_info and promotion_info.get('is_promotion'):
                                discount_amount = promotion_info.get('discount_amount', 0)
                                product_id = promotion_info.get('product_id', False)
                                description = promotion_info.get('description', 'Descuento Promoción')
                                
                                # Verificar si ya existe una línea de descuento en la orden
                                existing_discount_line = self.lines.filtered(
                                    lambda l: l.product_id.id == product_id and l.price_unit < 0
                                )
                                
                                if not existing_discount_line and discount_amount > 0 and product_id:
                                    # Agregar el descuento ANTES de generar la factura
                                    _logger.info('Agregando descuento de promoción a orden %s ANTES de generar factura (Descuento: %s)', 
                                               self.name, discount_amount)
                                    discount_result = self.add_promotion_discount_line(
                                        discount_amount,
                                        product_id,
                                        description
                                    )
                                    
                                    if discount_result.get('success'):
                                        _logger.info('Descuento agregado exitosamente a orden %s antes de generar factura', self.name)
                                    else:
                                        _logger.error('Error al agregar descuento antes de generar factura: %s', 
                                                    discount_result.get('error'))
                        except Exception as e:
                            _logger.error('Error al procesar información de promoción antes de generar factura: %s', str(e))
                            import traceback
                            _logger.error('Traceback: %s', traceback.format_exc())
        except Exception as e:
            _logger.error('Error al verificar promociones antes de generar factura para orden %s: %s', self.name, str(e))
            import traceback
            _logger.error('Traceback: %s', traceback.format_exc())
        
        # Llamar al método base para generar la factura
        # Ahora la factura se generará con el descuento ya aplicado
        return super(PosOrder, self)._generate_pos_order_invoice()
    
