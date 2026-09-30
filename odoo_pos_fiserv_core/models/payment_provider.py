# -*- coding: utf-8 -*-
"""
Extiende payment.provider con el código Fiserv ITD y credenciales compartidas.

El proveedor es el "driver" del bucle de consultas ITD: expone el timestamp,
el Query y el Reverse. Con múltiples POS el PosID viene de fiserv.pos.terminal.

El cobro desde **contabilidad** (``account.payment``) usa solo este proveedor y la
línea de método del diario, **sin** crear ``pos.payment.method`` ni vincular el diario al TPV.

Toda la capa HTTP es PRIVADA (prefijo ``_``): Odoo no expone por RPC los
métodos con guion bajo. En 17.0 eran públicos y cualquiera con acceso al
modelo podía disparar un POST a ITD desde el cliente web.
"""

import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config

from . import fiserv_utils

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    """
    Añade proveedor Fiserv ITD y parámetros de homologación multi-terminal.
    """

    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('fiserv', 'Fiserv ITD')],
        ondelete={'fiserv': 'set default'},
    )
    fiserv_is_multiple = fields.Boolean(
        string='Fiserv: múltiples POS',
        help='Si está activo, en el pago se elige un terminal de la lista.',
    )
    fiserv_url_webservice = fields.Char(
        string='Fiserv URL ITD',
        help='URL base del servicio ITD sin barra final (ej. https://testitd.firstdata.com/v2/ITDService).',
    )
    fiserv_system_id = fields.Char(
        string='SystemId',
        groups='base.group_system',
        help='Identificador único asignado por Fiserv al comercio (ITD). '
             'No sale en logs ni en el request guardado de las transacciones.',
    )
    fiserv_branch = fields.Char(
        string='Branch',
        help='Identificador de sucursal ITD (texto, hasta 100 caracteres).',
    )
    fiserv_client_app_id = fields.Char(
        string='ClientAppId',
        default='1',
        help='Identificador de caja / aplicación cliente en ITD.',
    )
    fiserv_terminal_ids = fields.One2many(
        comodel_name='fiserv.pos.terminal',
        inverse_name='payment_provider_id',
        string='Terminales (PosID)',
    )

    # ------------------------------------------------------------------
    # Arranque
    # ------------------------------------------------------------------
    @api.model
    def _register_hook(self):
        """Avisa al arrancar si el runtime no sirve para operar Fiserv."""
        res = super()._register_hook()
        self._fiserv_avisar_runtime_invalido()
        return res

    @api.model
    def _fiserv_avisar_runtime_invalido(self):
        """
        Avisa si hay un proveedor Fiserv activo en un server con ``--test-enable``.

        ``fiserv_safe_commit`` se saltea los commits con esa opción, porque en
        una corrida de tests un commit destruye los savepoints del caso. Pero
        la opción es del PROCESO: en un server que atiende pedidos reales con
        ella puesta, la transacción que se registra ANTES de hablar con ITD no
        se consolida, y si el proceso muere se pierde el rastro de un cobro
        que pudo haber pasado por el pinpad.

        No se levanta excepción: abortar el arranque sería peor que avisar.
        Sólo se avisa cuando el proceso se queda sirviendo.
        """
        if not config.get('test_enable') or config.get('stop_after_init'):
            return False
        activos = self.sudo().search_count([
            ('code', '=', 'fiserv'), ('state', '!=', 'disabled'),
        ])
        if not activos:
            return False
        _logger.warning(
            "Fiserv: hay %s proveedor(es) activo(s) en un servidor levantado "
            "con --test-enable. En ese runtime fiserv_safe_commit NO commitea "
            "y la transaccion registrada antes de hablar con ITD se pierde al "
            "primer rollback. NO operar Fiserv en este proceso.",
            activos,
        )
        return True

    # ------------------------------------------------------------------
    # Líneas de método de pago
    # ------------------------------------------------------------------
    def _ensure_payment_method_line(self, allow_create=True):
        """
        Gestiona las líneas de método Fiserv (inbound + outbound) del proveedor.

        Para Fiserv **no** delegamos en el core. El core (``account_payment``)
        asume **una sola** línea por proveedor: al cambiar ``journal_id`` mueve
        esa única línea con ``limit=1`` y, si el diario destino ya tiene una
        línea Fiserv (residuo, intento previo) o hay dos direcciones, choca con
        ``_check_payment_method_line_ids_multiplicity``. Como Fiserv define dos
        ``account.payment.method`` con ``code='fiserv'`` (inbound=cobros,
        outbound=devoluciones por terminal), ese supuesto no aplica.

        Garantía de este override: por cada método Fiserv queda **exactamente
        una** línea, en el diario actual del proveedor, con ``payment_provider_id``
        y el nombre del proveedor. Cualquier duplicado se fusiona (repuntando los
        pagos que lo referencien) en vez de crear una segunda línea y chocar.
        """
        self.ensure_one()
        if not self.id or self._get_code() != 'fiserv':
            return super()._ensure_payment_method_line(allow_create=allow_create)
        self._fiserv_ensure_payment_method_lines(allow_create=allow_create)

    def _fiserv_ensure_payment_method_lines(self, allow_create=True):
        """
        Deja una única línea por método Fiserv en el diario actual del proveedor.

        Principio (igual que el core): la línea del **propio proveedor** se
        **mueve**, nunca se borra. Lo que se borra es la línea residual/ajena
        que estorbe en el diario destino.

        19.0: la línea se crea CON cuenta de cobros pendientes
        (``payment_account_id``), igual que la crea el core. Sin ella, un pago
        confirmado no genera asiento, y sin asiento no hay nada que conciliar
        con la factura: el cobro quedaría registrado sin saldar nada.
        """
        if self.env.context.get('fiserv_skip_line_sync'):
            return
        self.ensure_one()
        line_model = self.env['account.payment.method.line'].sudo()
        # ``journal_id`` es computed/inverse NO almacenado: capturarlo UNA vez;
        # releerlo tras modificar líneas devuelve valores inconsistentes.
        target_journal = self.journal_id
        methods = self.env['account.payment.method'].sudo().search([('code', '=', 'fiserv')])
        for method in methods:
            ours = line_model.search([
                ('payment_method_id', '=', method.id),
                ('payment_provider_id', '=', self.id),
            ])

            if not target_journal:
                # Proveedor sin diario: no deben quedar sus líneas (paridad core).
                self._fiserv_remove_lines(ours, line_model.browse())
                continue

            # Líneas del mismo método que estorban en el diario destino y NO son
            # del proveedor (residuos sin proveedor, u otro proveedor).
            conflicts_on_target = line_model.search([
                ('payment_method_id', '=', method.id),
                ('journal_id', '=', target_journal.id),
                ('payment_provider_id', '!=', self.id),
            ])

            if ours:
                survivor = ours.filtered(lambda l: l.journal_id.id == target_journal.id)[:1] or ours[:1]
                self._fiserv_remove_lines((ours - survivor) | conflicts_on_target, survivor)
                vals = {}
                if survivor.journal_id.id != target_journal.id:
                    vals['journal_id'] = target_journal.id
                if survivor.name != self.name:
                    vals['name'] = self.name
                if not survivor.payment_account_id:
                    account_id = self._get_payment_method_outstanding_account_id(method)
                    if account_id:
                        vals['payment_account_id'] = account_id
                if vals:
                    survivor.write(vals)
            else:
                survivor = conflicts_on_target[:1]
                if survivor:
                    self._fiserv_remove_lines(conflicts_on_target - survivor, survivor)
                    survivor.write({'payment_provider_id': self.id, 'name': self.name})
                elif allow_create:
                    line_model.create({
                        'name': self.name,
                        'payment_method_id': method.id,
                        'journal_id': target_journal.id,
                        'payment_provider_id': self.id,
                        'payment_account_id': self._get_payment_method_outstanding_account_id(method),
                    })

    def _fiserv_remove_lines(self, lines, survivor):
        """
        Repunta los pagos de ``lines`` hacia ``survivor`` y elimina ``lines``.

        Las líneas propias se **desligan** del proveedor antes de borrar
        (``payment_provider_id = False``): Odoo impide borrar líneas ligadas a
        un provider enabled/test. Best-effort: si algo no se puede borrar, se
        loguea y se sigue (no se aborta el save).
        """
        lines = lines.exists()
        if not lines:
            return
        if survivor:
            pays = self.env['account.payment'].sudo().search([
                ('payment_method_line_id', 'in', lines.ids),
            ])
            if pays:
                pays.write({'payment_method_line_id': survivor.id})
        ours = lines.filtered(lambda line: line.payment_provider_id.id == self.id)
        if ours:
            ours.write({'payment_provider_id': False})
        try:
            with self.env.cr.savepoint():
                lines.unlink()
        except Exception as exc:  # noqa: BLE001 - best-effort, no abortar el save
            _logger.warning(
                'Fiserv: no se pudieron eliminar líneas de método %s (%s); '
                'revisar manualmente.', lines.ids, exc,
            )

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------
    def _fiserv_check_ready(self):
        """
        El proveedor tiene que estar habilitado y con credenciales para cobrar.

        El proveedor nace ``disabled`` y sin credenciales: enviar un cobro con
        un SystemId vacío no es un error de ITD, es un pedido que nunca debió
        salir. Se corta acá con un mensaje que dice qué falta.
        """
        self.ensure_one()
        if self.code != 'fiserv':
            raise UserError(_('El proveedor debe ser Fiserv ITD.'))
        if self.state == 'disabled':
            raise UserError(_(
                'El proveedor de pago «%s» está deshabilitado. Habilítelo en '
                'Contabilidad > Configuración > Proveedores de pago.', self.name))
        faltantes = []
        if not (self.fiserv_url_webservice or '').strip():
            faltantes.append(_('URL ITD'))
        if not (self.sudo().fiserv_system_id or '').strip():
            faltantes.append('SystemId')
        if not (self.fiserv_client_app_id or '').strip():
            faltantes.append('ClientAppId')
        if faltantes:
            raise UserError(_(
                'Faltan datos de conexión ITD en el proveedor %(provider)s: %(fields)s.',
                provider=self.name, fields=', '.join(faltantes)))

    # ------------------------------------------------------------------
    # Capa HTTP ITD (driver del bucle de consultas)
    # ------------------------------------------------------------------
    def _fiserv_base_url(self):
        self.ensure_one()
        return (self.fiserv_url_webservice or '').rstrip('/')

    def _fiserv_itd_post(self, path_suffix, data, log_label, extra_999_pos_warning=False):
        """POST a ITD con la URL del proveedor. Nunca levanta por transporte."""
        self.ensure_one()
        _base, response = fiserv_utils.fiserv_itd_http_post(
            self._fiserv_base_url(), path_suffix, data, log_label,
            extra_999_pos_warning=extra_999_pos_warning,
        )
        return response

    def _fiserv_timestamp(self):
        """
        Marca de tiempo ITD.

        Returns:
            str: ``yyyyMMddHHmmssSSS`` con milisegundos.
        """
        now = datetime.now()
        return now.strftime('%Y%m%d%H%M%S') + f'{int(now.microsecond / 1000):03d}'

    def _fiserv_itd_query(self, data):
        """processFinancialPurchaseQuery: estado de una transacción ITD."""
        return self._fiserv_itd_post(
            '/processFinancialPurchaseQuery', data, 'processFinancialPurchaseQuery')

    def _fiserv_itd_reverse(self, data):
        """processFinancialReverse: se envía cuando vence el tiempo en el pinpad."""
        return self._fiserv_itd_post(
            '/processFinancialReverse', data, 'processFinancialReverse')

    def _fiserv_itd_confirm(self, data):
        """processConfirmFinancialPurchase: tras leer la tarjeta (RC=12)."""
        return self._fiserv_itd_post(
            '/processConfirmFinancialPurchase', data, 'processConfirmFinancialPurchase')

    def _fiserv_itd_batch_query(self, data):
        """
        processCurrentTransactionsBatchQuery (Especificación ITD v3.5 pág. 66):
        transacciones del lote en curso de una terminal, sin afectar nada.
        """
        return self._fiserv_itd_post(
            '/processCurrentTransactionsBatchQuery', data,
            'processCurrentTransactionsBatchQuery')

    def _fiserv_identity_payload(self, pos_id, user_id=None):
        """Campos de identificación comunes a toda operación ITD."""
        self.ensure_one()
        return {
            'PosID': str(pos_id or ''),
            'SystemId': str(self.sudo().fiserv_system_id or ''),
            'Branch': (self.fiserv_branch or '').strip() or '',
            'ClientAppId': self.fiserv_client_app_id or '1',
            'UserId': str(user_id or self.env.user.id),
            'TransactionDateTimeyyyyMMddHHmmssSSS': self._fiserv_timestamp(),
        }

    def _fiserv_query_payload(self, operation_data, transaction_id):
        """Payload de Query para una operación ya iniciada."""
        self.ensure_one()
        return {
            'PosID': operation_data['PosID'],
            'SystemId': operation_data['SystemId'],
            'Branch': operation_data['Branch'],
            'ClientAppId': operation_data['ClientAppId'],
            'UserId': operation_data['UserId'],
            'TransactionDateTimeyyyyMMddHHmmssSSS': self._fiserv_timestamp(),
            'TransactionId': str(transaction_id).strip(),
        }

    def _fiserv_check_original_in_current_batch(self, pos_id, original_tx):
        """
        Determina si la transacción Fiserv original sigue en el lote actual del pinpad.

        Es el chequeo proactivo que decide anulación vs devolución según las
        reglas de Fiserv (Especificación ITD v3.5, preguntas frecuentes #1 y
        #2): la anulación solo es válida dentro del mismo lote.

        Returns:
            bool|None:
              - ``True``: mismo lote → se puede anular.
              - ``False``: el lote cambió → hay que ir directo a refund.
              - ``None``: no se pudo determinar (sin respuesta OK, sin datos).
                El llamador sigue con el void normal y el fallback reactivo.
        """
        self.ensure_one()
        if not original_tx:
            return None
        original_ticket = (original_tx.ticket_number or '').strip()
        original_batch = (original_tx.batch_number or '').strip()
        if not original_ticket and not original_batch:
            _logger.info(
                'Fiserv batch-check: tx original sin ticket_number ni batch_number; '
                'no concluyente'
            )
            return None

        payload = self._fiserv_identity_payload(pos_id)
        result = self._fiserv_itd_batch_query(payload)
        rc = str(result.get('ResponseCode', '999')).strip()
        if rc != '0':
            _logger.info(
                'Fiserv batch-check: ResponseCode=%s msg=%s; no concluyente',
                rc, result.get('msg') or '',
            )
            return None

        transactions = result.get('Transactions') or []
        if not transactions:
            # Lote actual vacío con RC=0: el pinpad cerró su lote. La tx
            # original no puede estar acá. Por regla Fiserv #1/#2 → refund.
            return False

        # Match preferido: ticket de la tx original en la lista del lote actual.
        if original_ticket:
            ticket_norm = original_ticket.lstrip('0')
            for tx in transactions:
                tx_ticket = str((tx or {}).get('Ticket', '') or '').strip()
                if tx_ticket and tx_ticket.lstrip('0') == ticket_norm:
                    return True
            return False

        # Fallback: comparar Batch (cuando no había ticket en la tx original).
        current_batch = ''
        for tx in transactions:
            b = str((tx or {}).get('Batch', '') or '').strip()
            if b:
                current_batch = b
                break
        if not current_batch:
            return None
        return current_batch.lstrip('0') == original_batch.lstrip('0')

    # ------------------------------------------------------------------
    # Payloads desde el pago contable
    # ------------------------------------------------------------------
    def _fiserv_ref_invoice_account_payment(self, account_payment):
        """
        Referencia de factura / pago para el campo InvoiceNumber de ITD (hasta 7 caracteres).

        Prioridad:
        1. ``fiserv_source_invoice_ids`` (facturas elegidas al registrar el pago).
        2. ``reconciled_invoice_ids`` (solo tras confirmar y conciliar).
        3. ``account.payment.id`` (fallback).

        Si hay una única factura, toma el sufijo numérico del ``name`` de la
        factura (p.ej. ``111-A-166`` → ``7 dígitos zfill``). Si hay varias o
        ninguna factura, fallback al id del pago.
        """
        pay = account_payment
        invoices = self.env['account.move']
        if 'fiserv_source_invoice_ids' in pay._fields and pay.fiserv_source_invoice_ids:
            invoices = pay.fiserv_source_invoice_ids
        elif 'reconciled_invoice_ids' in pay._fields and pay.reconciled_invoice_ids:
            invoices = pay.reconciled_invoice_ids
        if len(invoices) == 1:
            inv = invoices[0]
            raw_name = (inv.name or '').replace(' ', '')
            digits = ''.join(c for c in raw_name if c.isdigit())
            if len(digits) >= 7:
                return digits[-7:]
            if digits:
                return digits.zfill(7)[-7:]
            return str(inv.id)[-7:].zfill(7)
        return str(pay.id)[-7:].zfill(7)

    def _fiserv_resolve_pos_id_account_payment(self, account_payment):
        """
        PosID para ITD cuando el driver es el proveedor (sin ``pos.payment.method``).

        Raises:
            UserError: configuración incompleta.
        """
        self.ensure_one()
        account_payment.ensure_one()
        if self.code != 'fiserv':
            raise UserError(_('El proveedor debe ser Fiserv ITD.'))
        prov = self
        term = account_payment.fiserv_terminal_id
        terminals = prov.fiserv_terminal_ids

        if prov.fiserv_is_multiple:
            if term:
                if term.payment_provider_id != prov:
                    raise UserError(_(
                        'El terminal «%(t)s» no pertenece al proveedor Fiserv «%(p)s».',
                        t=term.display_name, p=prov.display_name))
                pos_id = (term.pos_id or '').strip()
                if pos_id:
                    return pos_id
            raise UserError(
                _('Seleccione el terminal Fiserv (PosID) en el pago (proveedor con múltiples terminales).')
            )

        if len(terminals) == 1:
            pos_id = (terminals[0].pos_id or '').strip()
            if pos_id:
                return pos_id
        if len(terminals) > 1:
            if term and term in terminals:
                pos_id = (term.pos_id or '').strip()
                if pos_id:
                    return pos_id
            raise UserError(
                _('Seleccione el terminal Fiserv en el pago: el proveedor tiene varios PosID configurados.')
            )
        raise UserError(_(
            'Configure al menos un terminal PosID en el proveedor de pago Fiserv «%s» '
            '(Contabilidad > Configuración > Terminales Fiserv).', prov.display_name))

    def _prepare_fiserv_itd_payload_for_account_payment(self, account_payment):
        """
        Arma ``processFinancialPurchase`` usando solo datos del proveedor y del pago contable.
        """
        self.ensure_one()
        account_payment.ensure_one()
        amount_cents = int(round(account_payment.amount * 100))
        if amount_cents <= 0:
            raise UserError(_('El importe del pago debe ser mayor que cero.'))

        currency_name = account_payment.currency_id.name
        currency_code = '840' if currency_name == 'USD' else '858'
        inv_num = self._fiserv_ref_invoice_account_payment(account_payment)
        pos_id = self._fiserv_resolve_pos_id_account_payment(account_payment)

        data = self._fiserv_identity_payload(pos_id)
        data.update({
            'Amount': str(amount_cents),
            'Quotas': 99,
            'Plan': 99,
            'Currency': currency_code,
            'TaxRefund': account_payment._fiserv_compute_tax_refund_cents(),
            'TaxAmount': account_payment._fiserv_compute_tax_amount_cents(),
            'TaxableAmount': str(amount_cents),
            'InvoiceAmount': str(amount_cents),
            'InvoiceNumber': inv_num,
            'Installments': 1,
            'TicketNumber': '',
            'NeedToReadCard': True,
        })
        return data

    def _prepare_fiserv_itd_void_payload_for_account_payment(self, account_payment, source_transaction):
        """
        Payload ``processFinancialPurchaseVoidByTicket`` desde proveedor (sin POS).
        """
        self.ensure_one()
        account_payment.ensure_one()
        source_transaction.ensure_one()
        if source_transaction.company_id != account_payment.company_id:
            raise UserError(
                _('La transacción original debe ser de la misma compañía que el pago.')
            )

        ticket = (source_transaction.ticket_number or '').strip()
        if not ticket:
            raise UserError(_(
                'La transacción de pago seleccionada no tiene número de ticket ITD; '
                'no se puede anular por ticket.'))

        acquirer = source_transaction.acquirer
        if acquirer is None or acquirer is False:
            acquirer = ''
        else:
            acquirer = str(acquirer).strip()
        pos_id = self._fiserv_resolve_pos_id_account_payment(account_payment)

        data = self._fiserv_identity_payload(pos_id)
        data.update({
            'TicketNumber': ticket,
            'Acquirer': acquirer,
        })
        return data

    def _prepare_fiserv_itd_refund_payload(
        self, source_transaction, pos_id, amount_cents, user_id, invoice_number=None
    ):
        """
        Payload ``processFinancialPurchaseRefund`` genérico desde el proveedor.

        Fiserv acepta devolución total o parcial; `amount_cents` puede ser menor al
        monto de la transacción original. La fecha original se toma de ``create_date``
        de ``source_transaction`` en formato ``yyMMdd``.
        """
        self.ensure_one()
        source_transaction.ensure_one()
        ticket = (source_transaction.ticket_number or '').strip()
        if not ticket:
            raise UserError(
                _('La transacción original no tiene ticket ITD; no se puede hacer devolución.')
            )
        original_dt = source_transaction.create_date
        if not original_dt:
            raise UserError(
                _('La transacción original no tiene fecha; no se puede hacer devolución.')
            )
        original_date_yyMMdd = original_dt.strftime('%y%m%d')

        currency_name = (source_transaction.currency_id.name or 'UYU')
        currency_code = '840' if currency_name == 'USD' else '858'

        # InvoiceNumber: la spec ITD v3.5 (pág. 41) lo limita a 7 caracteres y
        # los ejemplos son siempre numéricos. Si pasamos algo como "Pago/178"
        # el pinpad puede freezarse o rechazar la operación. Saneamos: solo
        # dígitos, máximo 7. Si la tx original no tenía dígitos en su
        # invoice_number, fallback al id de la tx con zfill.
        inv = invoice_number
        if inv is None:
            inv = source_transaction.invoice_number or ''
        inv_raw = str(inv).strip()
        digits = ''.join(c for c in inv_raw if c.isdigit())
        if len(digits) >= 7:
            inv = digits[-7:]
        elif digits:
            inv = digits.zfill(7)
        else:
            inv = str(source_transaction.id)[-7:].zfill(7)

        try:
            quotas = int(source_transaction.installments or 1)
            if quotas < 1:
                quotas = 1
        except (TypeError, ValueError):
            quotas = 1

        data = self._fiserv_identity_payload(pos_id, user_id=user_id)
        data.update({
            'TicketNumber': ticket,
            'OriginalTransactionDateyyMMdd': original_date_yyMMdd,
            'Amount': str(amount_cents),
            'Quotas': quotas,
            'Plan': 0,
            'Currency': currency_code,
            'TaxRefund': 0,
            'TaxableAmount': str(amount_cents),
            'InvoiceAmount': str(amount_cents),
            'InvoiceNumber': inv,
        })
        return data

    # ------------------------------------------------------------------
    # Inicio de operaciones (POST inicial)
    # ------------------------------------------------------------------
    def _fiserv_start_purchase(self, data):
        """processFinancialPurchase. Devuelve la respuesta inicial normalizada."""
        self.ensure_one()
        return self._fiserv_itd_post(
            '/processFinancialPurchase', data, 'processFinancialPurchase',
            extra_999_pos_warning=True,
        )

    def _fiserv_switch_void_to_refund(self, account_payment, void_data):
        """
        Construye y envía ``processFinancialPurchaseRefund`` en lugar de un void.

        Usa el ``fiserv_original_transaction_id`` del pago y el mismo PosID que
        el void original (``void_data['PosID']``).

        Returns:
            tuple: (refund_data, response_json).
        """
        self.ensure_one()
        source_tx = account_payment.fiserv_original_transaction_id
        if not source_tx:
            raise UserError(
                _('Falta la transacción Fiserv original en el pago; no se puede hacer devolución.')
            )
        refund_data = self._prepare_fiserv_itd_refund_payload(
            source_transaction=source_tx,
            pos_id=str(void_data.get('PosID', '')),
            amount_cents=int(round(account_payment.amount * 100)),
            user_id=self.env.user.id,
        )
        response = self._fiserv_itd_post(
            '/processFinancialPurchaseRefund', refund_data, 'processFinancialPurchaseRefund')
        return refund_data, response

    def _fiserv_start_void_or_refund(self, account_payment, void_data):
        """
        Anulación por ticket, o devolución si el lote de la venta ya cerró.

        Antes del void se consulta el lote actual del pinpad. Si cambió, se
        salta el void y se envía directamente ``processFinancialPurchaseRefund``.
        Si no es concluyente, void normal con dos redes reactivas: RC 109/110
        al inicio (acá) y posResponseCode 21/25 al final del Query (en el
        worker).

        Un fallo de TRANSPORTE en el void NO dispara el refund: el void pudo
        haber llegado, y mandar además un refund podría devolver dos veces.

        Returns:
            tuple: (data realmente enviada, response_json).
        """
        self.ensure_one()
        original_tx = account_payment.fiserv_original_transaction_id
        in_current_batch = None
        if original_tx:
            in_current_batch = self._fiserv_check_original_in_current_batch(
                void_data.get('PosID', ''), original_tx)

        if in_current_batch is False:
            _logger.info(
                'Fiserv void→refund preventivo: el lote de la tx original ya cerró. '
                'account_payment=%s', account_payment.id,
            )
            return self._fiserv_switch_void_to_refund(account_payment, void_data)

        response = self._fiserv_itd_post(
            '/processFinancialPurchaseVoidByTicket', void_data,
            'processFinancialPurchaseVoidByTicket',
        )
        rc = str(response.get('ResponseCode', '999')).strip()
        if rc in fiserv_utils.FISERV_ITD_RC_VOID_SHOULD_REFUND:
            _logger.info(
                'Fiserv void rechazó RC=%s (ticket fuera del lote actual). '
                'Fallback a processFinancialPurchaseRefund. account_payment=%s',
                rc, account_payment.id,
            )
            return self._fiserv_switch_void_to_refund(account_payment, void_data)
        return void_data, response
