# -*- coding: utf-8 -*-
"""
Extensión del modelo pos.order para soporte de promociones OCA

Este módulo agrega funcionalidad para:
- Agregar líneas de descuento por promociones
- Obtener totales actualizados de órdenes
"""

import json
import logging

from odoo import models, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión del modelo pos.order para promociones OCA
    """
    _inherit = 'pos.order'

    def _associate_oca_transactions(self):
        """
        Tras enlazar transacciones OCA, alinea pos.payment.amount con el importe real
        cobrado en el pinpad (payment.transaction.amount) cuando hay promoción.
        El POS suele enviar el importe previo al descuento (500); la tx queda en 400.

        También recalcula cabecera de la orden por si la factura ya pasó y solo queda
        alinear totales en pantalla.
        """
        super()._associate_oca_transactions()
        for order in self:
            order._oca_promo_sync_payment_amounts_from_transactions()
            order._oca_promo_recompute_pos_order_header_amounts()

    def _oca_promo_get_oca_transaction_for_pos_payment(self, pay):
        """
        Resuelve ``payment.transaction`` OCA para un ``pos.payment`` usando el
        many2one o, si falta, el ``transaction_id`` del pinpad (char).

        Usado para alinear importes y sumar descuentos antes de facturar aunque
        ``payment_transaction_id`` aún no esté persistido.
        """
        tx = pay.payment_transaction_id
        if tx:
            return tx.sudo()
        tid = str(getattr(pay, 'transaction_id', None) or '').strip()
        if not tid:
            return self.env['payment.transaction']
        oca_provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'oca')], limit=1
        )
        if not oca_provider:
            return self.env['payment.transaction']
        return self.env['payment.transaction'].sudo().search(
            [
                ('oca_transaction_id', '=', tid),
                ('provider_id', '=', oca_provider.id),
                ('state', 'in', ['pending', 'done']),
            ],
            order='id desc',
            limit=1,
        )

    def _oca_promo_recompute_pos_order_header_amounts(self):
        """
        En Odoo 17, ``amount_total``, ``amount_tax`` y ``amount_paid`` en
        ``pos.order`` son Float persistidos (no ``@api.depends``). Tras modificar
        líneas o importes de pago hay que recalcularlos; el estándar es
        ``_compute_batch_amount_all`` (agrega líneas y pagos en BD).
        """
        self.ensure_one()
        if hasattr(self, '_compute_batch_amount_all'):
            self._compute_batch_amount_all()
            _logger.info(
                'OCA promo: cabecera pos.order recalculada | orden=%s total=%s paid=%s tax=%s',
                self.name,
                self.amount_total,
                self.amount_paid,
                self.amount_tax,
            )
        elif hasattr(self, '_onchange_amount_all'):
            self._onchange_amount_all()
            self.env.cr.flush()

    def _oca_promo_sync_payment_amounts_from_transactions(self):
        """
        Para cada pago OCA con transacción promocional, escribe amount = tx.amount
        si hay diferencia relevante.
        """
        for pay in self.payment_ids.filtered(
            lambda p: p.payment_method_id.use_payment_terminal == 'oca'
        ):
            tx = self._oca_promo_get_oca_transaction_for_pos_payment(pay)
            if not tx:
                continue
            if not pay.payment_transaction_id:
                pay.sudo().write({'payment_transaction_id': tx.id})
            if not getattr(tx, 'is_promotion', False):
                continue
            tx_amt = float(tx.amount or 0.0)
            pay_amt = float(pay.amount or 0.0)
            if abs(pay_amt - tx_amt) < 0.01:
                continue
            _logger.info(
                'OCA promo: alineando pos.payment id=%s amount %.2f -> %.2f (tx %s, orden %s)',
                pay.id,
                pay_amt,
                tx_amt,
                tx.oca_transaction_id,
                self.name,
            )
            pay.sudo().write({'amount': tx_amt})
            try:
                pay.sudo().write({'is_promotion': True})
            except Exception:
                pass

    def _oca_promo_collect_discount_totals_from_payments(self):
        """
        Suma discount_amount (TTC) de promotion_info en todas las transacciones OCA
        promocionales ligadas a los pagos de esta orden.

        Returns:
            tuple: (total_discount_ttc, product_id, description, promotion_id)
        """
        self.ensure_one()
        total_ttc = 0.0
        product_id = False
        description = 'Descuento Promoción'
        promotion_id = False
        for payment in self.payment_ids.filtered(
            lambda p: p.payment_method_id.use_payment_terminal == 'oca'
        ):
            tx = self._oca_promo_get_oca_transaction_for_pos_payment(payment)
            if not tx or not tx.is_promotion:
                continue
            try:
                complete_response = json.loads(tx.oca_complete_response or '{}')
                promotion_info = complete_response.get('promotion_info', {})
                if isinstance(promotion_info, str):
                    promotion_info = json.loads(promotion_info) or {}
            except (TypeError, ValueError, json.JSONDecodeError) as err:
                _logger.warning(
                    'OCA promo: promotion_info inválido en tx %s: %s',
                    tx.oca_transaction_id,
                    err,
                )
                continue
            if not promotion_info or not promotion_info.get('is_promotion'):
                continue
            try:
                amt = float(promotion_info.get('discount_amount', 0) or 0.0)
            except (TypeError, ValueError):
                amt = 0.0
            total_ttc += amt
            if not product_id and promotion_info.get('product_id'):
                product_id = promotion_info.get('product_id')
                description = promotion_info.get('description') or description
                promotion_id = promotion_info.get('promotion_id') or False
        return total_ttc, product_id, description, promotion_id

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
                                # Verificar incompatibilidades antes de agregar la línea de descuento.
                                # Si existe incompatibilidad con promociones estándar (ej. cupones / lealtad),
                                # se lanza ValidationError para impedir que la orden y el flujo de pago
                                # continúen con una combinación inválida.
                                should_apply = True
                                if promotion_id:
                                    promotion = self.env['payment.method.promotion'].browse(promotion_id)
                                    if promotion.exists():
                                        applied_ids = self.env[
                                            "payment.method.promotion"
                                        ].collect_applied_loyalty_program_ids_from_pos_order(order)
                                        blocked, block_msg = promotion.get_incompatibility_payment_block_for_applied_programs(
                                            applied_ids
                                        )
                                        if blocked:
                                            _logger.warning(
                                                'No se puede aplicar promoción %s (ID: %s): %s',
                                                promotion.name,
                                                promotion.id,
                                                block_msg,
                                            )
                                            raise ValidationError(block_msg)
                                
                                if should_apply:
                                    # Bloque: no insertar línea aquí — el POS ya la agrega por cobro vía RPC
                                    # (add_promotion_discount_line con el descuento de ESE pago). Hacerlo también
                                    # desde create duplicaba montos (ej. -500) y desalineaba pagos.
                                    _logger.info(
                                        'OCA promo en create: sin add_promotion_discount_line | orden=%s | tx=%s',
                                        order.name,
                                        oca_transaction.oca_transaction_id,
                                    )
                                    try:
                                        if not oca_transaction.pos_order_id:
                                            oca_transaction.pos_order_id = order.id
                                        if oca_payments and oca_payments[0]:
                                            oca_transaction.pos_payment_id = oca_payments[0].id
                                            oca_payments[0].payment_transaction_id = oca_transaction.id
                                    except Exception as link_err:
                                        _logger.warning(
                                            'OCA promo create: error al enlazar transacción: %s',
                                            link_err,
                                        )
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
            # Bloqueo explícito: promoción OCA incompatible con lealtad ya aplicada en este pedido
            if promotion_id:
                promo = self.env['payment.method.promotion'].browse(promotion_id)
                if promo.exists():
                    applied_ids = self.env[
                        "payment.method.promotion"
                    ].collect_applied_loyalty_program_ids_from_pos_order(self)
                    blocked, block_msg = (
                        promo.get_incompatibility_payment_block_for_applied_programs(
                            applied_ids
                        )
                    )
                    if blocked:
                        _logger.warning(
                            'add_promotion_discount_line rechazado por incompatibilidad (orden %s, promo %s)',
                            self.id,
                            promotion_id,
                        )
                        return {
                            'success': False,
                            'error': block_msg,
                            'incompatible_promotion': True,
                        }

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
            
            # Bloque: localizar línea de descuento existente (mismo producto) para acumular
            # varios cobros OCA parciales (ej. 50 + 50 = 100 de descuento TTC total).
            existing_discount_line = self.lines.filtered(
                lambda l: l.product_id.id == product_id and l.price_unit < 0
            )

            # Bloque: descuento TTC acumulado = lo ya reflejado en la línea + incremento de este cobro.
            prev_gross_ttc = 0.0
            if existing_discount_line:
                el = existing_discount_line[0]
                prev_gross_ttc = abs(float(el.price_subtotal_incl or 0.0))
                if prev_gross_ttc < 1e-6:
                    prev_gross_ttc = abs(float(el.price_subtotal or 0.0))
                    if el.tax_ids and prev_gross_ttc > 1e-6:
                        total_tax_rate = sum(t.amount for t in el.tax_ids) / 100.0
                        if not any(t.price_include for t in el.tax_ids):
                            prev_gross_ttc = prev_gross_ttc * (1.0 + total_tax_rate)
            cumulative_gross_ttc = prev_gross_ttc + float(discount_amount)
            _logger.info(
                'OCA promo línea descuento: incremento TTC=%s | acumulado TTC=%s (orden %s)',
                discount_amount,
                cumulative_gross_ttc,
                self.name,
            )

            # Bloque: impuestos de la línea de descuento (mismos criterios que antes).
            tax_ids = []
            for line in self.lines:
                if line.product_id.id != product_id and line.tax_ids:
                    for tax in line.tax_ids:
                        if tax.id not in tax_ids:
                            tax_ids.append(tax.id)
            if not tax_ids and product.taxes_id:
                tax_ids = product.taxes_id.ids
            if not tax_ids:
                basic_tax = self.env['account.tax'].search([
                    ('amount', '=', 22.0),
                    ('type_tax_use', '=', 'sale'),
                    ('company_id', '=', self.company_id.id)
                ], limit=1)
                if basic_tax:
                    tax_ids = [basic_tax.id]

            # Bloque: a partir del descuento TTC acumulado, obtener price_unit y subtotales
            # (misma lógica para alta y actualización; antes la rama "update" ponía mal price_subtotal_incl).
            qty = 1.0
            if tax_ids:
                taxes = self.env['account.tax'].browse(tax_ids)
                price_include = any(tax.price_include for tax in taxes)
                if price_include:
                    price_unit = -abs(cumulative_gross_ttc)
                else:
                    total_tax_rate = sum(tax.amount for tax in taxes) / 100.0
                    discount_net = cumulative_gross_ttc / (1.0 + total_tax_rate)
                    price_unit = -abs(discount_net)
            else:
                price_unit = -abs(cumulative_gross_ttc)

            calculated_price_subtotal = price_unit * qty
            if tax_ids:
                taxes = self.env['account.tax'].browse(tax_ids)
                total_tax_rate = sum(tax.amount for tax in taxes) / 100.0
                if any(t.price_include for t in taxes):
                    calculated_price_subtotal_incl = calculated_price_subtotal
                else:
                    calculated_price_subtotal_incl = calculated_price_subtotal * (1.0 + total_tax_rate)
            else:
                calculated_price_subtotal_incl = calculated_price_subtotal

            line_vals = {
                'product_id': product_id,
                'qty': qty,
                'price_unit': price_unit,
                'name': description or f'Descuento Promoción - {product.name}',
                'tax_ids': [(6, 0, tax_ids)] if tax_ids else [(5, 0, 0)],
                'full_product_name': description or f'Descuento Promoción - {product.name}',
                'discount': 0.0,
                'price_subtotal': calculated_price_subtotal,
                'price_subtotal_incl': calculated_price_subtotal_incl,
            }

            if existing_discount_line:
                _logger.warning(
                    'Actualizando línea de descuento promoción existente (acumulado TTC=%s)',
                    cumulative_gross_ttc,
                )
                existing_discount_line[0].write(line_vals)
                try:
                    existing_discount_line[0]._compute_amount_line_all()
                except AttributeError:
                    try:
                        existing_discount_line[0]._compute_amount()
                    except Exception:
                        pass
                except Exception as e:
                    _logger.warning('No se pudo recalcular línea de descuento: %s', str(e))
                line_id = existing_discount_line[0].id
            else:
                discount_line_new = self.env['pos.order.line'].new({
                    'order_id': self.id,
                    **line_vals,
                })
                try:
                    discount_line_new._onchange_qty()
                except AttributeError:
                    pass
                discount_line_vals = discount_line_new._convert_to_write(discount_line_new._cache)
                discount_line_vals.setdefault('price_subtotal', calculated_price_subtotal)
                discount_line_vals.setdefault('price_subtotal_incl', calculated_price_subtotal_incl)
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

            # Bloque: Odoo 17 — cabecera pos.order desde líneas y pagos reales
            self._oca_promo_recompute_pos_order_header_amounts()
            
            # Log detallado del descuento calculado para verificación
            discount_line = self.env['pos.order.line'].browse(line_id)
            _logger.info('Línea de descuento agregada exitosamente a orden %s: Línea ID %s', 
                        self.name, line_id)
            _logger.info(
                '  Descuento incremento TTC (este cobro): %s | acumulado en línea (TTC): %s',
                discount_amount,
                cumulative_gross_ttc,
            )
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
            # Bloque: Odoo 17 — amount_total/amount_paid son Float persistidos; refrescar con API estándar.
            if hasattr(self, '_compute_batch_amount_all'):
                self._compute_batch_amount_all()
            elif hasattr(self, '_compute_amount_all'):
                self._compute_amount_all()
            lines = self.lines
            amount_total_from_lines = sum(lines.mapped('price_subtotal_incl'))
            amount_untaxed_from_lines = sum(lines.mapped('price_subtotal'))

            return {
                'newTotal': self.amount_total,
                'newTaxableAmount': self.amount_untaxed,
                'newInvoiceAmount': self.amount_total,
                'newTotalFromLines': amount_total_from_lines,
                'newTaxableFromLines': amount_untaxed_from_lines,
            }
        except Exception as e:
            _logger.error('Error al obtener totales de orden %s: %s', self.name, str(e))
            # Bloque: fallback seguro con montos de cabecera si el cálculo por líneas falla.
            return {
                'newTotal': self.amount_total,
                'newTaxableAmount': self.amount_untaxed,
                'newInvoiceAmount': self.amount_total
            }
    
    def _generate_pos_order_invoice(self):
        """
        Antes de ``super()`` (creación de factura y ``account.payment``):

        1. Alinear ``pos.payment.amount`` con ``payment.transaction.amount`` en
           promos OCA. Si esto ocurre solo en ``_associate_oca_transactions``
           (después de facturar), los asientos quedan en 500+300 en lugar de 400+400.

        2. Completar línea de descuento con la suma de descuentos de todas las txs.

        3. Recalcular cabecera ``pos.order`` (Odoo 17: ``amount_total`` no se
           actualiza solo al agregar líneas; hace falta ``_compute_batch_amount_all``).
        """
        for order in self:
            order._oca_promo_sync_payment_amounts_from_transactions()
            try:
                total_ttc, product_id, description, promotion_id = (
                    order._oca_promo_collect_discount_totals_from_payments()
                )
                if total_ttc > 0 and product_id:
                    if promotion_id:
                        promotion = order.env['payment.method.promotion'].browse(
                            promotion_id
                        )
                        if promotion.exists():
                            applied_ids = order.env[
                                'payment.method.promotion'
                            ].collect_applied_loyalty_program_ids_from_pos_order(order)
                            blocked, block_msg = (
                                promotion.get_incompatibility_payment_block_for_applied_programs(
                                    applied_ids
                                )
                            )
                            if blocked:
                                _logger.warning(
                                    'Factura bloqueada por promo OCA incompatible: %s',
                                    block_msg,
                                )
                                raise ValidationError(block_msg)

                    existing_discount_line = order.lines.filtered(
                        lambda l, pid=product_id: l.product_id.id == pid
                        and l.price_unit < 0
                    )
                    current_gross = 0.0
                    if existing_discount_line:
                        el = existing_discount_line[0]
                        current_gross = abs(float(el.price_subtotal_incl or 0.0))
                        if current_gross < 1e-6:
                            current_gross = abs(float(el.price_subtotal or 0.0))
                            if el.tax_ids and current_gross > 1e-6:
                                total_tax_rate = sum(t.amount for t in el.tax_ids) / 100.0
                                if not any(t.price_include for t in el.tax_ids):
                                    current_gross = current_gross * (
                                        1.0 + total_tax_rate
                                    )

                    increment = max(0.0, float(total_ttc) - current_gross)
                    if increment > 0.01:
                        _logger.info(
                            'OCA promo factura: descuento TTC total en txs=%s | ya en línea=%s | '
                            'incremento a aplicar=%s | orden=%s',
                            total_ttc,
                            current_gross,
                            increment,
                            order.name,
                        )
                        discount_result = order.add_promotion_discount_line(
                            increment,
                            product_id,
                            description,
                            promotion_id=promotion_id,
                        )
                        if not discount_result.get('success'):
                            _logger.error(
                                'Error al completar descuento promo antes de facturar: %s',
                                discount_result.get('error'),
                            )
            except ValidationError:
                raise
            except Exception as e:
                _logger.error(
                    'Error al verificar promociones antes de generar factura para orden %s: %s',
                    order.name,
                    str(e),
                )
                import traceback
                _logger.error('Traceback: %s', traceback.format_exc())

            order._oca_promo_recompute_pos_order_header_amounts()

        return super(PosOrder, self)._generate_pos_order_invoice()
    
