# -*- coding: utf-8 -*-
"""
Modelo para extender pos.order con funcionalidades Fiserv ITD
"""

import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión básica del modelo pos.order
    """
    _inherit = 'pos.order'

    fiserv_voucher_transaction_id = fields.Many2one(
        'payment.transaction',
        string='Transacción Fiserv (voucher tarjeta)',
        compute='_compute_fiserv_voucher_transaction_id',
        help='Transacción Fiserv ITD más reciente asociada a la orden (p. ej. reporte PDF de voucher).',
    )

    @api.depends('state', 'payment_ids')
    def _compute_fiserv_voucher_transaction_id(self):
        """
        Resuelve la misma transacción que get_fiserv_voucher_html_for_pos_print para poder
        renderizar el voucher en reportes QWeb sin duplicar lógica en plantillas.

        No se usa @depends(..., 'payment_ids.payment_transaction_id'): ese campo lo añaden
        odoo_pos_oca u odoo_pos_fiserv_pos_payment; si no están instalados, el registro
        falla al cargar el modelo.
        """
        # Bloque: búsqueda por orden y proveedor Fiserv (alineado con get_fiserv_voucher_html_for_pos_print).
        PaymentTransaction = self.env['payment.transaction'].sudo()
        for order in self:
            transaction = PaymentTransaction.search(
                [
                    ('pos_order_id', '=', order.id),
                    ('provider_id.code', '=', 'fiserv'),
                ],
                order='id desc',
                limit=1,
            )
            order.fiserv_voucher_transaction_id = transaction

    @api.model
    def get_fiserv_voucher_html_for_pos_print(self, order_id, raise_on_missing=True):
        """
        Obtiene el HTML del voucher Fiserv para una orden POS.

        Este método está pensado para el flujo de impresión desde POS (QZ Tray):
        localiza la transacción Fiserv más reciente asociada a la orden y renderiza
        el reporte QWeb del voucher.

        Args:
            order_id (int): ID de la orden POS en el backend.

        Args:
            raise_on_missing (bool): Si False, ante ausencia de transacción Fiserv o
                configuración de reporte devuelve string vacío (para que el POS
                pueda seguir imprimiendo otros documentos).

        Returns:
            str: HTML del voucher Fiserv listo para impresión, o '' si no corresponde.
        """
        # Bloque: validar orden para evitar errores de render con IDs inválidos.
        order = self.browse(order_id)
        if not order.exists():
            _logger.warning(
                "Voucher Fiserv: orden no encontrada para impresión | order_id=%s",
                order_id,
            )
            if raise_on_missing:
                raise UserError(_("No se encontró la orden para imprimir el voucher Fiserv."))
            return ''

        # Bloque: localizar la transacción Fiserv más reciente asociada a la orden.
        transaction = self.env['payment.transaction'].sudo().search(
            [
                ('pos_order_id', '=', order.id),
                ('provider_id.code', '=', 'fiserv'),
            ],
            order='id desc',
            limit=1,
        )
        if not transaction:
            _logger.warning(
                "Voucher Fiserv: no hay transacción Fiserv asociada a la orden | order=%s (id=%s)",
                order.name,
                order.id,
            )
            if raise_on_missing:
                raise UserError(
                    _("No se encontró una transacción Fiserv para generar el voucher de esta orden.")
                )
            return ''

        # Bloque: obtener acción de reporte y renderizar QWeb HTML del voucher.
        report_action = self.env.ref(
            'odoo_pos_fiserv.action_report_payment_transaction_fiserv_voucher',
            raise_if_not_found=False,
        )
        if not report_action:
            _logger.error("Voucher Fiserv: no se encontró la acción de reporte del voucher.")
            if raise_on_missing:
                raise UserError(_("No se encontró la configuración del reporte de voucher Fiserv."))
            return ''

        html_result, _mime = self.env['ir.actions.report'].sudo()._render_qweb_html(
            report_action.report_name, transaction.ids
        )
        html_str = html_result.decode('utf-8') if isinstance(html_result, bytes) else str(html_result)
        _logger.info(
            "Voucher Fiserv: HTML generado correctamente | order=%s | tx=%s | html_len=%s",
            order.name,
            transaction.reference or transaction.id,
            len(html_str),
        )
        return html_str

    def _find_payment_transaction_for_pos_receipt(self, order):
        """
        Localiza la transacción de tarjeta asociada a la orden POS.

        Orden de búsqueda: por orden+proveedor Fiserv, por líneas de pago con
        payment_transaction_id, luego cualquier transacción enlazada a la orden.
        """
        PaymentTransaction = self.env['payment.transaction'].sudo()
        fiserv_provider = self.env['payment.provider'].sudo().search([('code', '=', 'fiserv')], limit=1)
        # Bloque: caso ideal — transacción Fiserv con pos_order_id.
        transaction = PaymentTransaction.search(
            [
                ('pos_order_id', '=', order.id),
                ('provider_id.code', '=', 'fiserv'),
            ],
            order='id desc',
            limit=1,
        )
        if transaction:
            return transaction
        # Bloque: transacción enlazada al pago POS (a veces pos_order_id se asocia después).
        # payment_transaction_id solo existe si está OCA u odoo_pos_fiserv_pos_payment.
        if "payment_transaction_id" in self.env["pos.payment"]._fields:
            for pay in order.payment_ids:
                if pay.payment_transaction_id:
                    t = pay.payment_transaction_id.sudo()
                    if fiserv_provider and t.provider_id == fiserv_provider:
                        return t
            for pay in order.payment_ids:
                if pay.payment_transaction_id:
                    return pay.payment_transaction_id.sudo()
        # Bloque: último recurso — cualquier transacción con pos_order_id.
        return PaymentTransaction.search(
            [('pos_order_id', '=', order.id)],
            order='id desc',
            limit=1,
        )

    @api.model
    def get_fiserv_voucher_dict_for_pos_receipt(self, order_id=False, pos_reference=False):
        """
        Devuelve un diccionario con los datos del voucher Fiserv para el diseño de recibo POS
        (p. ej. «Recibo con CFE (FORUM)»). Si no hay transacción, devuelve {}.

        Args:
            order_id (int|bool): ID backend de pos.order (False si solo se usa referencia).
            pos_reference (str|bool): pos_reference o name de la orden si aún no hay server_id.

        Returns:
            dict: Campos listos para el template del recibo; vacío si no aplica.
        """
        # Bloque: resolver orden por id o por referencia (impresión sin server_id sincronizado).
        order = self.sudo().browse(int(order_id)) if order_id else self.env['pos.order'].sudo().browse()
        if order_id and not order.exists():
            _logger.warning(
                "Voucher recibo POS: orden id=%s no existe; se intenta por referencia=%r",
                order_id,
                pos_reference,
            )
            order = self.sudo().browse()
        if (not order or not order.exists()) and pos_reference:
            order = self.sudo().search([('pos_reference', '=', pos_reference)], limit=1)
            if not order:
                order = self.sudo().search([('name', '=', pos_reference)], limit=1)
        if not order.exists():
            _logger.warning(
                "Voucher recibo POS: sin orden resuelta | order_id=%s | pos_reference=%r",
                order_id,
                pos_reference,
            )
            return {}
        transaction = self._find_payment_transaction_for_pos_receipt(order)
        if not transaction:
            _logger.warning(
                "Voucher recibo POS: sin payment.transaction | orden=%s (id=%s) | pagos=%s",
                order.name,
                order.id,
                len(order.payment_ids),
            )
            return {}
        # Bloque: sucursal / RUT (misma prioridad que en reportes QWeb).
        branch_partner = False
        if (
            order.config_id
            and order.config_id.picking_type_id
            and order.config_id.picking_type_id.warehouse_id
            and order.config_id.picking_type_id.warehouse_id.partner_id
        ):
            branch_partner = order.config_id.picking_type_id.warehouse_id.partner_id
        elif order.config_id and order.config_id.company_id and order.config_id.company_id.partner_id:
            branch_partner = order.config_id.company_id.partner_id
        elif order.company_id and order.company_id.partner_id:
            branch_partner = order.company_id.partner_id
        # Bloque: máscara de tarjeta y fechas en zona horaria del usuario.
        card_bin = transaction.card_bin or ''
        card_last = transaction.card_last_four or ''
        card_masked = f'{card_bin}******{card_last}' if (card_bin or card_last) else '************'
        # Bloque: fechas en TZ del usuario (usar fields.Datetime.context_timestamp: pos.order no siempre expone context_timestamp).
        create_local = False
        if transaction.create_date:
            create_local = fields.Datetime.context_timestamp(order, transaction.create_date)
        date_str = create_local.strftime('%d/%m/%Y') if create_local else ''
        time_str = create_local.strftime('%H:%M') if create_local else ''
        datetime_str = create_local.strftime('%d/%m/%Y %H:%M:%S') if create_local else ''
        result = {
            'has_voucher': True,
            'show_client_copy': True,
            'issuer_name': transaction.issuer_name or '',
            'acquirer': transaction.acquirer or '',
            'merchant_number': transaction.merchant_number or '',
            'pos_id': transaction.pos_id or '',
            'ticket_number': transaction.ticket_number or '',
            'batch_number': transaction.batch_number or '',
            'authorization_code': transaction.authorization_code or '',
            'invoice_number': transaction.invoice_number or '',
            'installments': transaction.installments or 0,
            'issuer_code': transaction.issuer_code or '',
            'card_masked': card_masked,
            'amount': transaction.amount,
            'date_str': date_str,
            'time_str': time_str,
            'datetime_str': datetime_str,
            'partner_name': order.partner_id.name or '',
            'company_name': order.company_id.name or '',
            'branch_street': branch_partner.street or '' if branch_partner else '',
            'branch_vat': branch_partner.vat or '' if branch_partner else '',
            'voucher_ref': transaction.ticket_number or transaction.reference or '',
        }
        _logger.info(
            "Voucher recibo POS: OK | orden=%s (id=%s) | tx_id=%s | ticket=%s | show_client_copy=%s",
            order.name,
            order.id,
            transaction.id,
            result.get('ticket_number'),
            result.get('show_client_copy'),
        )
        return result

    @api.model
    def get_fiserv_voucher_transaction_id_for_pos_print(self, order_id=False, pos_reference=False):
        """
        Devuelve el id de ``payment.transaction`` Fiserv asociado al recibo, o False.
        Usado desde el POS para imprimir solo el PDF/HTML del voucher sin duplicar lógica.
        """
        order = self.sudo().browse(int(order_id)) if order_id else self.env['pos.order'].sudo().browse()
        if order_id and not order.exists():
            order = self.sudo().browse()
        if (not order or not order.exists()) and pos_reference:
            order = self.sudo().search([('pos_reference', '=', pos_reference)], limit=1)
            if not order:
                order = self.sudo().search([('name', '=', pos_reference)], limit=1)
        if not order.exists():
            return False
        transaction = self._find_payment_transaction_for_pos_receipt(order)
        return transaction.id if transaction else False

    def get_change_ticket_barcode_data_uri(self):
        """
        Genera un data URI PNG (Code128) con el nº de orden para el reporte PDF/HTML.

        El ``<img src="/report/barcode/...">`` no siempre se renderiza en PDF (wkhtmltopdf
        sin URL absoluta); embeber base64 garantiza que el código de barras se vea.
        """
        self.ensure_one()
        value = (self.pos_reference or self.name or "").strip()
        if not value:
            return False
        try:
            png = self.env["ir.actions.report"].barcode(
                "Code128", value, width=300, height=80
            )
        except Exception as err:
            _logger.debug(
                "Ticket cambio: no se generó Code128 | orden=%s | valor=%r | %s",
                self.id,
                value,
                err,
            )
            return False
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para permitir asociación posterior de
        transacciones Fiserv. La asociación real se hace en _process_order
        después de que se crean las líneas de pago (_process_payment_lines),
        porque en create() aún no existen payment_ids.
        """
        return super(PosOrder, self).create(vals)

    @api.model
    def _process_order(self, order, draft, existing_order):
        """
        Tras procesar las líneas de pago, asocia las transacciones Fiserv a esta
        orden por referencia (pos.payment.transaction_id = payment.transaction.fiserv_transaction_id).
        """
        result = super(PosOrder, self)._process_order(order, draft, existing_order)
        pos_order = self.browse(result) if isinstance(result, int) else result
        pos_order._associate_fiserv_transactions()
        return result

    def _associate_fiserv_transactions(self):
        """
        Asocia transacciones Fiserv con esta orden usando la referencia de transacción
        cuando está disponible, para evitar ambigüedad cuando hay varios pagos del
        mismo monto en la sesión.

        Flujo:
        1. El frontend guarda en la línea de pago el ID de transacción Fiserv
           (transaction_id / origin_transaction_id) y se persiste en pos.payment.transaction_id.
        2. Al crear la orden, para cada pago Fiserv se busca payment.transaction por
           fiserv_transaction_id = pos.payment.transaction_id (referencia unívoca).
        3. Si no hay transaction_id en el pago, se hace fallback a coincidencia por monto
           (comportamiento anterior, para compatibilidad).
        """
        try:
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            session_id = getattr(self, 'session_id', None)
            session_id_value = session_id.id if session_id else 'Unknown'

            _logger.info(
                'Buscando transacciones Fiserv para asociar con orden: %s (Sesión: %s)',
                order_name, session_id_value
            )

            fiserv_payments = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'fiserv'
            )

            if not fiserv_payments:
                _logger.info(
                    'La orden %s no tiene pagos Fiserv aún, programando verificación posterior...',
                    order_name
                )
                self._schedule_fiserv_association_check()
                return

            _logger.info('Orden %s tiene %s pagos Fiserv', order_name, len(fiserv_payments))

            # Proveedor Fiserv para filtrar transacciones
            fiserv_provider = self.env['payment.provider'].sudo().search(
                [('code', '=', 'fiserv')], limit=1
            )
            if not fiserv_provider:
                _logger.warning('No se encontró proveedor Fiserv; asociación por referencia no disponible.')

            for fiserv_payment in fiserv_payments:
                payment_name = getattr(fiserv_payment, 'name', 'Unknown') or 'Unknown'
                payment_amount = getattr(fiserv_payment, 'amount', 0.0)
                payment_tid = getattr(fiserv_payment, 'transaction_id', None) or ''

                _logger.info(
                    'Procesando pago Fiserv: %s (Monto: %s, transaction_id=%s)',
                    payment_name, payment_amount, payment_tid or '(vacío)'
                )

                matching_transaction = None
                match_by_reference = False

                # 1) Asociación por referencia: pos.payment.transaction_id = payment.transaction.fiserv_transaction_id
                if payment_tid and fiserv_provider:
                    tx_by_ref = self.env['payment.transaction'].sudo().search([
                        ('fiserv_transaction_id', '=', payment_tid),
                        ('provider_id', '=', fiserv_provider.id),
                        ('pos_order_id', '=', False),
                        ('state', 'in', ['pending', 'done']),
                    ], limit=1)
                    if tx_by_ref:
                        matching_transaction = tx_by_ref
                        match_by_reference = True
                        _logger.info(
                            'Transacción Fiserv encontrada por referencia (fiserv_transaction_id=%s) -> reference=%s',
                            payment_tid, matching_transaction.reference
                        )

                # 2) Fallback: coincidencia por monto (cuando no hay transaction_id o no se encontró por ref)
                if not matching_transaction:
                    orphan_domain = [
                        ('fiserv_transaction_id', '!=', False),
                        ('pos_order_id', '=', False),
                        ('state', 'in', ['pending', 'done']),
                    ]
                    if fiserv_provider:
                        orphan_domain.append(('provider_id', '=', fiserv_provider.id))
                    orphaned_transactions = self.env['payment.transaction'].sudo().search(orphan_domain)
                    best_score = 0
                    for transaction in orphaned_transactions:
                        if transaction.pos_order_id:
                            continue
                        score = 0
                        if abs(transaction.amount - payment_amount) < 0.01:
                            score = 100
                        elif abs(transaction.amount - payment_amount) < 1.0:
                            score = 50
                        if score > best_score:
                            best_score = score
                            matching_transaction = transaction
                    if matching_transaction:
                        _logger.info(
                            'Transacción Fiserv asociada por monto (fallback): %s (%.2f)',
                            matching_transaction.fiserv_transaction_id, matching_transaction.amount
                        )

                if matching_transaction:
                    matching_transaction.pos_order_id = self.id
                    matching_transaction.pos_payment_id = fiserv_payment.id
                    if order_name and order_name != 'Unknown':
                        matching_transaction.invoice_number = order_name
                    _logger.info(
                        'Transacción Fiserv asociada a orden: %s -> Orden: %s, Pago: %s (por_ref=%s)',
                        matching_transaction.reference or matching_transaction.fiserv_transaction_id,
                        order_name, payment_name, match_by_reference
                    )
                else:
                    _logger.warning(
                        'No se encontró transacción Fiserv para el pago: %s (Monto: %s, transaction_id=%s)',
                        payment_name, payment_amount, payment_tid or '(vacío)'
                    )

            self._diagnose_fiserv_associations()

        except Exception as e:
            _logger.error('Error al asociar transacciones Fiserv con orden ID %s: %s', self.id, str(e))
    
    def _schedule_fiserv_association_check(self):
        """
        Programa una verificación posterior para asociar transacciones Fiserv
        cuando se creen los pagos
        """
        try:
            # En lugar de usar threading, vamos a usar un enfoque más simple
            # que no cause problemas de cursor cerrado
            order_id = self.id
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            
            _logger.info('Programada verificación diferida de asociación Fiserv para orden: %s (ID: %s)',
                        order_name, order_id)

            # Por ahora, no ejecutamos la verificación diferida para evitar problemas de cursor
            # La asociación se hará cuando se cree el pago Fiserv

        except Exception as e:
            _logger.error('Error al programar verificación de asociación Fiserv: %s', str(e))
    
    def _diagnose_fiserv_associations(self):
        """
        Ejecuta diagnóstico de asociaciones Fiserv para esta orden
        """
        try:
            # Obtener el nombre de la orden de forma segura
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            
            # Buscar transacciones Fiserv asociadas a esta orden
            associated_transactions = self.env['payment.transaction'].sudo().search([
                ('pos_order_id', '=', self.id),
                ('fiserv_transaction_id', '!=', False)
            ])
            
            _logger.info('=== DIAGNÓSTICO DE ASOCIACIONES FISERV PARA ORDEN %s ===', order_name)
            _logger.info('Transacciones Fiserv asociadas: %s', len(associated_transactions))
            
            for transaction in associated_transactions:
                payment_name = getattr(transaction.pos_payment_id, 'name', 'None') if transaction.pos_payment_id else 'None'
                invoice_number = getattr(transaction, 'invoice_number', 'None')
                
                _logger.info('  - Transacción: %s, Pago: %s, Factura: %s',
                           transaction.fiserv_transaction_id,
                           payment_name,
                           invoice_number)

            # Verificar pagos Fiserv sin transacción asociada
            fiserv_pmts = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'fiserv'
            )

            unassociated_payments = []
            for payment in fiserv_pmts:
                transaction = self.env['payment.transaction'].sudo().search([
                    ('pos_payment_id', '=', payment.id),
                    ('fiserv_transaction_id', '!=', False)
                ], limit=1)
                
                if not transaction:
                    unassociated_payments.append(payment)
            
            _logger.info('Pagos Fiserv sin transacción asociada: %s', len(unassociated_payments))
            for payment in unassociated_payments:
                payment_name = getattr(payment, 'name', 'Unknown') or 'Unknown'
                payment_amount = getattr(payment, 'amount', 0.0)
                _logger.info('  - Pago: %s (Monto: %s)', payment_name, payment_amount)
            
            _logger.info('=== FIN DIAGNÓSTICO ===')
            
        except Exception as e:
            _logger.error('Error en diagnóstico de asociaciones Fiserv para orden ID %s: %s', self.id, str(e)) 