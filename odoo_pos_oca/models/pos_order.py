# -*- coding: utf-8 -*-
"""
Modelo para extender pos.order con funcionalidades básicas
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

    oca_voucher_transaction_id = fields.Many2one(
        'payment.transaction',
        string='Transacción OCA (voucher tarjeta)',
        compute='_compute_oca_voucher_transaction_id',
        help='Transacción OCA más reciente asociada a la orden (p. ej. reporte PDF de voucher).',
    )

    @api.depends('state', 'payment_ids', 'payment_ids.payment_transaction_id')
    def _compute_oca_voucher_transaction_id(self):
        """
        Resuelve la misma transacción que get_oca_voucher_html_for_pos_print para poder
        renderizar el voucher en reportes QWeb sin duplicar lógica en plantillas.
        """
        # Bloque: búsqueda por orden y proveedor OCA (alineado con get_oca_voucher_html_for_pos_print).
        PaymentTransaction = self.env['payment.transaction'].sudo()
        for order in self:
            transaction = PaymentTransaction.search(
                [
                    ('pos_order_id', '=', order.id),
                    ('provider_id.code', '=', 'oca'),
                ],
                order='id desc',
                limit=1,
            )
            order.oca_voucher_transaction_id = transaction

    @api.model
    def get_oca_voucher_html_for_pos_print(self, order_id, raise_on_missing=True):
        """
        Obtiene el HTML del voucher OCA para una orden POS.

        Este método está pensado para el flujo de impresión desde POS (QZ Tray):
        localiza la transacción OCA más reciente asociada a la orden y renderiza
        el reporte QWeb del voucher.

        Args:
            order_id (int): ID de la orden POS en el backend.

        Args:
            raise_on_missing (bool): Si False, ante ausencia de transacción OCA o
                configuración de reporte devuelve string vacío (para que el POS
                pueda seguir imprimiendo otros documentos).

        Returns:
            str: HTML del voucher OCA listo para impresión, o '' si no corresponde.
        """
        # Bloque: validar orden para evitar errores de render con IDs inválidos.
        order = self.browse(order_id)
        if not order.exists():
            _logger.warning(
                "Voucher OCA: orden no encontrada para impresión | order_id=%s",
                order_id,
            )
            if raise_on_missing:
                raise UserError(_("No se encontró la orden para imprimir el voucher OCA."))
            return ''

        # Bloque: localizar TODAS las transacciones OCA de la orden.
        transactions = self._find_all_payment_transactions_for_pos_receipt(order)
        if not transactions:
            _logger.warning(
                "Voucher OCA: no hay transacción OCA asociada a la orden | order=%s (id=%s)",
                order.name,
                order.id,
            )
            if raise_on_missing:
                raise UserError(
                    _("No se encontró una transacción OCA para generar el voucher de esta orden.")
                )
            return ''

        # Bloque: obtener acción de reporte y renderizar QWeb HTML de todos los vouchers.
        report_action = self.env.ref(
            'odoo_pos_oca.action_report_payment_transaction_oca_voucher',
            raise_if_not_found=False,
        )
        if not report_action:
            _logger.error("Voucher OCA: no se encontró la acción de reporte del voucher.")
            if raise_on_missing:
                raise UserError(_("No se encontró la configuración del reporte de voucher OCA."))
            return ''

        html_result, _mime = self.env['ir.actions.report'].sudo()._render_qweb_html(
            report_action.report_name, transactions.ids
        )
        html_str = html_result.decode('utf-8') if isinstance(html_result, bytes) else str(html_result)
        _logger.info(
            "Voucher OCA: HTML generado correctamente | order=%s | txs=%s | html_len=%s",
            order.name,
            transactions.ids,
            len(html_str),
        )
        return html_str

    @api.model
    def get_oca_voucher_print_data(self, order_id):
        """
        Resuelve el reporte y los IDs necesarios para descargar el voucher OCA
        como PDF desde el frontend (fallback de QZ Tray).

        Devuelve la misma forma de contrato que ``get_loyalty_coupon_code_print_data``
        del módulo ``pos_forum_qz_print``: un dict con ``doc_ids`` y ``report_xml_id``,
        listos para invocar ``this.report.doAction(report_xml_id, doc_ids)`` en el JS.
        Si no hay voucher OCA aplicable a la orden, devuelve ``{}`` y el caller debe
        omitir la descarga (no es error).

        Args:
            order_id (int): ID backend de ``pos.order``.

        Returns:
            dict: ``{'doc_ids': [int, ...], 'report_xml_id': str}`` o ``{}``.
        """
        order = self.browse(order_id)
        if not order.exists():
            return {}
        transactions = self._find_all_payment_transactions_for_pos_receipt(order)
        if not transactions:
            return {}
        report = self.env.ref(
            'odoo_pos_oca.action_report_payment_transaction_oca_voucher',
            raise_if_not_found=False,
        )
        if not report:
            return {}
        return {
            'doc_ids': transactions.ids,
            'report_xml_id': 'odoo_pos_oca.action_report_payment_transaction_oca_voucher',
        }

    def _filter_printable_voucher_transactions(self, order, transactions):
        """Excluye transacciones cuyo método de pago POS tiene no_print_voucher activo."""
        excluded_tx_ids = {
            pay.payment_transaction_id.id
            for pay in order.payment_ids
            if pay.payment_transaction_id
            and getattr(pay.payment_method_id, 'no_print_voucher', False)
        }
        if not excluded_tx_ids:
            return transactions
        return transactions.filtered(lambda tx: tx.id not in excluded_tx_ids)

    def _find_all_payment_transactions_for_pos_receipt(self, order):
        """Localiza TODAS las transacciones OCA de la orden para el recibo multi-voucher."""
        PaymentTransaction = self.env['payment.transaction'].sudo()
        transactions = PaymentTransaction.search(
            [('pos_order_id', '=', order.id), ('provider_id.code', '=', 'oca')],
            order='id asc',
        )
        if transactions:
            return self._filter_printable_voucher_transactions(order, transactions)
        seen = set()
        tx_ids = []
        for pay in order.payment_ids:
            if pay.payment_transaction_id and pay.payment_transaction_id.id not in seen:
                seen.add(pay.payment_transaction_id.id)
                tx_ids.append(pay.payment_transaction_id.id)
        if tx_ids:
            return self._filter_printable_voucher_transactions(
                order, PaymentTransaction.browse(tx_ids)
            )
        return self._filter_printable_voucher_transactions(
            order,
            PaymentTransaction.search([('pos_order_id', '=', order.id)], order='id asc'),
        )

    def _find_payment_transaction_for_pos_receipt(self, order):
        """
        Localiza la transacción de tarjeta asociada a la orden POS.

        Orden de búsqueda: por orden+proveedor OCA, por líneas de pago con
        payment_transaction_id, luego cualquier transacción enlazada a la orden.
        """
        PaymentTransaction = self.env['payment.transaction'].sudo()
        oca_provider = self.env['payment.provider'].sudo().search([('code', '=', 'oca')], limit=1)
        # Bloque: caso ideal — transacción OCA con pos_order_id.
        transaction = PaymentTransaction.search(
            [
                ('pos_order_id', '=', order.id),
                ('provider_id.code', '=', 'oca'),
            ],
            order='id desc',
            limit=1,
        )
        if transaction:
            return transaction
        # Bloque: transacción enlazada al pago POS (a veces pos_order_id se asocia después).
        for pay in order.payment_ids:
            if pay.payment_transaction_id:
                t = pay.payment_transaction_id.sudo()
                if oca_provider and t.provider_id == oca_provider:
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
    def get_oca_voucher_dict_for_pos_receipt(self, order_id=False, pos_reference=False):
        """
        Devuelve un diccionario con los datos del voucher OCA para el diseño de recibo POS
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
        transactions = self._find_all_payment_transactions_for_pos_receipt(order)
        if not transactions:
            _logger.warning(
                "Voucher recibo POS: sin payment.transaction | orden=%s (id=%s) | pagos=%s",
                order.name,
                order.id,
                len(order.payment_ids),
            )
            return []
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
        results = []
        for transaction in transactions:
            # Bloque: máscara de tarjeta y fechas en zona horaria del usuario.
            card_bin = transaction.card_bin or ''
            card_last = transaction.card_last_four or ''
            card_masked = f'{card_bin}******{card_last}' if (card_bin or card_last) else '************'
            create_local = False
            if transaction.create_date:
                create_local = fields.Datetime.context_timestamp(order, transaction.create_date)
            date_str = create_local.strftime('%d/%m/%Y') if create_local else ''
            time_str = create_local.strftime('%H:%M') if create_local else ''
            datetime_str = create_local.strftime('%d/%m/%Y %H:%M:%S') if create_local else ''
            results.append({
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
                'tax_refund_amount': transaction.tax_refund_amount or 0.0,
                # Importe gravado: el ticket OCA lo expone como Amount / 1.22 (IVA 22% UY).
                'taxable_amount': round((transaction.amount or 0.0) / 1.22, 2),
                # Código DGI del comercio (Ley 19210); vacío si no está configurado.
                'dgi_code': transaction.provider_id.oca_dgi_code or '',
                'date_str': date_str,
                'time_str': time_str,
                'datetime_str': datetime_str,
                'partner_name': order.partner_id.name or '',
                'company_name': order.company_id.name or '',
                'branch_street': branch_partner.street or '' if branch_partner else '',
                'branch_vat': branch_partner.vat or '' if branch_partner else '',
                'voucher_ref': transaction.ticket_number or transaction.reference or '',
            })
        _logger.info(
            "Voucher recibo POS: OK | orden=%s (id=%s) | %d vouchers | tickets=%s",
            order.name,
            order.id,
            len(results),
            [r.get('ticket_number') for r in results],
        )
        return results

    @api.model
    def get_oca_voucher_transaction_id_for_pos_print(self, order_id=False, pos_reference=False):
        """
        Devuelve el id de ``payment.transaction`` OCA asociado al recibo, o False.
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
            # PNG ancho/alta resolución: al estirarse a width:100% en el ticket
            # mantiene nitidez (wkhtmltopdf escala con height:auto preservando
            # la proporción ~5:1).
            png = self.env["ir.actions.report"].barcode(
                "Code128", value, width=600, height=80
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
        transacciones OCA. La asociación real se hace en _process_order
        después de que se crean las líneas de pago (_process_payment_lines),
        porque en create() aún no existen payment_ids.
        """
        return super(PosOrder, self).create(vals)

    @api.model
    def _process_order(self, order, draft, existing_order):
        """
        Tras procesar las líneas de pago, asocia las transacciones OCA a esta
        orden por referencia (pos.payment.transaction_id = payment.transaction.oca_transaction_id).
        """
        result = super(PosOrder, self)._process_order(order, draft, existing_order)
        pos_order = self.browse(result) if isinstance(result, int) else result
        pos_order._associate_oca_transactions()
        return result

    def _generate_pos_order_invoice(self):
        """
        Si el pago ya fue capturado por el pinpad OCA (``payment.transaction`` en
        ``done``), atrapar cualquier excepción del flujo de facturación para que
        la orden quede persistida como ``paid`` y el POS no se freeze.

        Motivo: el dinero ya se cobró en el pinpad; si la factura UY falla por
        datos faltantes (p.ej. receptor sin RUT), la orden debe quedar guardada
        con ``to_invoice=False`` y el problema se resuelve a posteriori desde el
        backoffice. Reventar aquí hace que Odoo revierta la orden a draft y el
        POS pierda sync con la pinpad.
        """
        self.ensure_one()
        has_oca_tx = bool(self.env['payment.transaction'].sudo().search_count([
            ('pos_order_id', '=', self.id),
            ('provider_id.code', '=', 'oca'),
            ('state', '=', 'done'),
        ]))
        if not has_oca_tx:
            return super()._generate_pos_order_invoice()
        try:
            return super()._generate_pos_order_invoice()
        except Exception as exc:
            _logger.error(
                "POS OCA: fallo generando factura orden %s; orden queda paid "
                "con to_invoice=False. Error: %s",
                self.name, exc, exc_info=True,
            )
            # No se usa savepoint: UserError no aborta la tx PG. Posibles
            # ``account.move`` en draft parciales quedan para corrección manual.
            try:
                self.sudo().write({'to_invoice': False})
            except Exception:
                _logger.debug("POS OCA: no se pudo setear to_invoice=False", exc_info=True)
            try:
                self.message_post(body=_(
                    "No se pudo generar la factura automáticamente tras cobrar en "
                    "terminal OCA: %s.\n\nLa transacción fue aprobada; la orden "
                    "queda pagada. Corrija los datos y regenere la factura desde "
                    "el backend."
                ) % (str(exc) or exc.__class__.__name__))
            except Exception:
                _logger.debug("POS OCA: no se pudo postear mensaje en chatter", exc_info=True)
            return False

    def _associate_oca_transactions(self):
        """
        Asocia transacciones OCA con esta orden usando la referencia de transacción
        cuando está disponible, para evitar ambigüedad cuando hay varios pagos del
        mismo monto en la sesión.

        Flujo:
        1. El frontend guarda en la línea de pago el ID de transacción OCA
           (transaction_id / origin_transaction_id) y se persiste en pos.payment.transaction_id.
        2. Al crear la orden, para cada pago OCA se busca payment.transaction por
           oca_transaction_id = pos.payment.transaction_id (referencia unívoca).
           No se exige pos_order_id vacío: pos.payment puede haber vinculado ya la
           transacción (p. ej. promoción OCA con monto distinto al del pago).
        3. Si no hay transaction_id en el pago, se hace fallback a coincidencia por monto
           (legado). Si hay transaction_id y no se encuentra fila, NO se usa ese fallback
           para no enganchar una transacción antigua del mismo monto (p. ej. 600).
        """
        try:
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            session_id = getattr(self, 'session_id', None)
            session_id_value = session_id.id if session_id else 'Unknown'

            _logger.info(
                'Buscando transacciones OCA para asociar con orden: %s (Sesión: %s)',
                order_name, session_id_value
            )

            oca_payments = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'oca'
            )

            if not oca_payments:
                _logger.info(
                    'La orden %s no tiene pagos OCA aún, programando verificación posterior...',
                    order_name
                )
                self._schedule_oca_association_check()
                return

            _logger.info('Orden %s tiene %s pagos OCA', order_name, len(oca_payments))

            # Proveedor OCA para filtrar transacciones
            oca_provider = self.env['payment.provider'].sudo().search(
                [('code', '=', 'oca')], limit=1
            )
            if not oca_provider:
                _logger.warning('No se encontró proveedor OCA; asociación por referencia no disponible.')

            for oca_payment in oca_payments:
                payment_name = getattr(oca_payment, 'name', 'Unknown') or 'Unknown'
                payment_amount = getattr(oca_payment, 'amount', 0.0)
                payment_tid = getattr(oca_payment, 'transaction_id', None) or ''

                _logger.info(
                    'Procesando pago OCA: %s (Monto: %s, transaction_id=%s)',
                    payment_name, payment_amount, payment_tid or '(vacío)'
                )

                matching_transaction = None
                match_by_reference = False

                # --- 1) Por referencia: ID OCA del pinpad en pos.payment.transaction_id ---
                if payment_tid and oca_provider:
                    tid_key = str(payment_tid).strip()
                    tx_by_ref = self.env['payment.transaction'].sudo().search([
                        ('oca_transaction_id', '=', tid_key),
                        ('provider_id', '=', oca_provider.id),
                        ('state', 'in', ['pending', 'done']),
                    ], order='id desc', limit=1)
                    if tx_by_ref:
                        # --- No reutilizar tx ya ligada a otro pos.payment ---
                        if (
                            tx_by_ref.pos_payment_id
                            and tx_by_ref.pos_payment_id.id != oca_payment.id
                        ):
                            _logger.warning(
                                'OCA POS: transacción oca_transaction_id=%s ya en pago %s; '
                                'no se reasigna a %s.',
                                tid_key,
                                getattr(tx_by_ref.pos_payment_id, 'name', tx_by_ref.pos_payment_id.id),
                                payment_name,
                            )
                        # --- No reutilizar una transacción ya ligada a otra orden ---
                        elif (
                            tx_by_ref.pos_order_id
                            and tx_by_ref.pos_order_id.id != self.id
                        ):
                            _logger.warning(
                                'OCA POS: transacción oca_transaction_id=%s ya en orden %s; '
                                'no se reasigna a %s.',
                                tid_key,
                                tx_by_ref.pos_order_id.name,
                                order_name,
                            )
                        else:
                            matching_transaction = tx_by_ref
                            match_by_reference = True
                            _logger.info(
                                'Transacción OCA encontrada por referencia '
                                '(oca_transaction_id=%s) -> reference=%s',
                                payment_tid,
                                matching_transaction.reference,
                            )

                # --- 2) Fallback por monto: solo si el pago no trae transaction_id OCA ---
                # Con promo, el pago puede ser 600 y la transacción 480; si aquí se busca 600
                # se engancha un cobro viejo. Si hay tid, el cajero ya apuntó a una operación.
                if not matching_transaction and not payment_tid:
                    orphan_domain = [
                        ('oca_transaction_id', '!=', False),
                        ('pos_order_id', '=', False),
                        ('state', 'in', ['pending', 'done']),
                    ]
                    if oca_provider:
                        orphan_domain.append(('provider_id', '=', oca_provider.id))
                    orphaned_transactions = self.env['payment.transaction'].sudo().search(orphan_domain)
                    best_score = 0
                    for transaction in orphaned_transactions:
                        if transaction.pos_order_id:
                            continue
                        if transaction.pos_payment_id:
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
                            'Transacción OCA asociada por monto (fallback): %s (%.2f)',
                            matching_transaction.oca_transaction_id, matching_transaction.amount
                        )

                if matching_transaction:
                    matching_transaction.pos_order_id = self.id
                    matching_transaction.pos_payment_id = oca_payment.id
                    if order_name and order_name != 'Unknown':
                        matching_transaction.invoice_number = order_name
                    _logger.info(
                        'Transacción OCA asociada a orden: %s -> Orden: %s, Pago: %s (por_ref=%s)',
                        matching_transaction.reference or matching_transaction.oca_transaction_id,
                        order_name, payment_name, match_by_reference
                    )
                else:
                    _logger.warning(
                        'No se encontró transacción OCA para el pago: %s (Monto: %s, transaction_id=%s)',
                        payment_name, payment_amount, payment_tid or '(vacío)'
                    )

            # Bloque: coherencia final — no dos pagos con la misma tx si la tx ya tiene otro pos_payment_id;
            # ni pago con transaction_id distinto al oca_transaction_id de la fila enlazada.
            for oca_pay in self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'oca'
            ):
                tx = oca_pay.payment_transaction_id
                if not tx:
                    continue
                pay_nm = getattr(oca_pay, 'name', None) or str(oca_pay.id)
                if tx.pos_payment_id and tx.pos_payment_id.id != oca_pay.id:
                    _logger.warning(
                        'OCA POS: pago %s desvinculado (tx %s ya asignada a otro pago)',
                        pay_nm,
                        tx.oca_transaction_id,
                    )
                    oca_pay.payment_transaction_id = False
                    continue
                tid_on_pay = str(getattr(oca_pay, 'transaction_id', None) or '').strip()
                if tid_on_pay and tx.oca_transaction_id and str(tx.oca_transaction_id).strip() != tid_on_pay:
                    _logger.warning(
                        'OCA POS: pago %s desvinculado (tid pago=%s ≠ oca_transaction_id=%s)',
                        pay_nm,
                        tid_on_pay,
                        tx.oca_transaction_id,
                    )
                    oca_pay.payment_transaction_id = False

            self._diagnose_oca_associations()

        except Exception as e:
            _logger.error('Error al asociar transacciones OCA con orden ID %s: %s', self.id, str(e))
    
    def _schedule_oca_association_check(self):
        """
        Programa una verificación posterior para asociar transacciones OCA
        cuando se creen los pagos
        """
        try:
            # En lugar de usar threading, vamos a usar un enfoque más simple
            # que no cause problemas de cursor cerrado
            order_id = self.id
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            
            _logger.info('Programada verificación diferida de asociación OCA para orden: %s (ID: %s)', 
                        order_name, order_id)
            
            # Por ahora, no ejecutamos la verificación diferida para evitar problemas de cursor
            # La asociación se hará cuando se cree el pago OCA
            
        except Exception as e:
            _logger.error('Error al programar verificación de asociación OCA: %s', str(e))
    
    def _diagnose_oca_associations(self):
        """
        Ejecuta diagnóstico de asociaciones OCA para esta orden
        """
        try:
            # Obtener el nombre de la orden de forma segura
            order_name = getattr(self, 'name', 'Unknown') or 'Unknown'
            
            # Buscar transacciones OCA asociadas a esta orden
            associated_transactions = self.env['payment.transaction'].sudo().search([
                ('pos_order_id', '=', self.id),
                ('oca_transaction_id', '!=', False)
            ])
            
            _logger.info('=== DIAGNÓSTICO DE ASOCIACIONES OCA PARA ORDEN %s ===', order_name)
            _logger.info('Transacciones OCA asociadas: %s', len(associated_transactions))
            
            for transaction in associated_transactions:
                payment_name = getattr(transaction.pos_payment_id, 'name', 'None') if transaction.pos_payment_id else 'None'
                invoice_number = getattr(transaction, 'invoice_number', 'None')
                
                _logger.info('  - Transacción: %s, Pago: %s, Factura: %s', 
                           transaction.oca_transaction_id, 
                           payment_name,
                           invoice_number)
            
            # Verificar pagos OCA sin transacción asociada
            oca_payments = self.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == 'oca'
            )
            
            unassociated_payments = []
            for payment in oca_payments:
                transaction = self.env['payment.transaction'].sudo().search([
                    ('pos_payment_id', '=', payment.id),
                    ('oca_transaction_id', '!=', False)
                ], limit=1)
                
                if not transaction:
                    unassociated_payments.append(payment)
            
            _logger.info('Pagos OCA sin transacción asociada: %s', len(unassociated_payments))
            for payment in unassociated_payments:
                payment_name = getattr(payment, 'name', 'Unknown') or 'Unknown'
                payment_amount = getattr(payment, 'amount', 0.0)
                _logger.info('  - Pago: %s (Monto: %s)', payment_name, payment_amount)
            
            _logger.info('=== FIN DIAGNÓSTICO ===')
            
        except Exception as e:
            _logger.error('Error en diagnóstico de asociaciones OCA para orden ID %s: %s', self.id, str(e)) 