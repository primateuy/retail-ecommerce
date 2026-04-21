# -*- coding: utf-8 -*-
"""
Extiende payment.provider con el código Fiserv ITD y credenciales compartidas.

Los campos de conexión (URL, SystemId, Branch) se pueden copiar al método de
pago POS mediante onchange; con múltiples POS, el PosID viene de fiserv.pos.terminal.

El cobro desde **contabilidad** (``account.payment``) puede usar solo este proveedor y la
línea de método del diario, **sin** crear ``pos.payment.method`` ni vincular el diario al TPV.
"""

import logging
import pprint
import threading

import requests

from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

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
        help='Si está activo, en el método de pago POS se elige un terminal de la lista.',
    )
    fiserv_url_webservice = fields.Char(
        string='Fiserv URL ITD',
        help='URL base del servicio ITD sin barra final (ej. https://testitd.firstdata.com/v2/ITDService).',
    )
    fiserv_system_id = fields.Char(
        string='SystemId',
        help='Identificador único asignado por Fiserv al comercio (ITD).',
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

    def get_formatted_timestamp(self):
        """
        Marca de tiempo ITD (misma lógica que ``pos.payment.method``).

        Returns:
            str: ``yyyyMMddHHmmssSSS`` con milisegundos.
        """
        self.ensure_one()
        now = datetime.now()
        return now.strftime('%Y%m%d%H%M%S') + f'{int(now.microsecond / 1000):03d}'

    def processFinancialPurchaseQuery(self, data, base_url_endpoint):
        """
        Consulta el estado de una transacción ITD (processFinancialPurchaseQuery).

        Mismo contrato que ``pos.payment.method.processFinancialPurchaseQuery``: el hilo
        ``fiserv_run_purchase_query_loop`` invoca este método sobre el driver; cuando el cobro
        es desde contabilidad el driver es ``payment.provider``, que antes no exponía la API.

        Args:
            data (dict): Payload de consulta (TransactionId, PosID, timestamp, etc.).
            base_url_endpoint (str): URL base ITD sin barra final.

        Returns:
            dict: JSON normalizado por ITD (ResponseCode, TransactionId, …).
        """
        self.ensure_one()
        from .fiserv_utils import _fiserv_normalize_itd_http_response

        endpoint = (base_url_endpoint or '').rstrip('/') + '/processFinancialPurchaseQuery'
        headers = {'Content-Type': 'application/json'}
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        return response_json

    def processFinancialReverse(self, data, base_url_endpoint):
        """
        Envía processFinancialReverse a ITD cuando el tiempo de la operación en pinpad expira.

        El bucle Query llama a este método en el mismo driver que Query; con contabilidad el
        driver es ``payment.provider``.

        Args:
            data (dict): Payload de reversión (alineado al usado desde POS).
            base_url_endpoint (str): URL base ITD.

        Returns:
            dict: Respuesta ITD normalizada.
        """
        self.ensure_one()
        from .fiserv_utils import _fiserv_normalize_itd_http_response

        _logger.info(
            'processFinancialReverse (payment.provider) by user #%d:\n%s',
            self.env.uid,
            pprint.pformat(data),
        )
        endpoint = (base_url_endpoint or '').rstrip('/') + '/processFinancialReverse'
        headers = {'Content-Type': 'application/json'}
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        _logger.info('processFinancialReverse Response:\n%s', pprint.pformat(response_json))
        return response_json

    def _fiserv_ref_invoice_account_payment(self, account_payment):
        """
        Referencia de factura / pago para el campo InvoiceNumber de ITD (hasta 7 caracteres).

        Prioridad:
        1. ``fiserv_source_invoice_ids`` (lo llena el wizard custom de registro
           de pago antes de postear). Es la fuente real de las facturas
           seleccionadas, disponible con el pago en draft.
        2. ``reconciled_invoice_ids`` (solo tras postear y reconciliar).
        3. ``account.payment.id`` (fallback).

        Si hay una única factura, toma el sufijo numérico del ``name`` de la
        factura (p.ej. ``111-A-166`` → ``7 dígitos zfill``). Si hay varias o
        ninguna factura, fallback al id del pago.

        Args:
            account_payment (account.payment): Pago contable.

        Returns:
            str: Sufijo numérico para ITD (7 caracteres).
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

        Args:
            account_payment (account.payment): Borrador con terminal opcional.

        Returns:
            str: PosID no vacío.

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
                    raise UserError(
                        _(
                            'El terminal «%(t)s» no pertenece al proveedor Fiserv «%(p)s».'
                        )
                        % {'t': term.display_name, 'p': prov.display_name}
                    )
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
        raise UserError(
            _(
                'Configure al menos un terminal PosID en el proveedor de pago Fiserv «%s» '
                '(Contabilidad / Pagos en línea).'
            )
            % prov.display_name
        )

    def _prepare_fiserv_itd_payload_for_account_payment(self, account_payment, pos_session):
        """
        Arma ``processFinancialPurchase`` usando solo datos del proveedor y del pago contable.

        Args:
            account_payment (account.payment): Borrador.
            pos_session (pos.session): Vacío en flujo contable directo.

        Returns:
            dict: Payload ITD.
        """
        self.ensure_one()
        account_payment.ensure_one()
        if pos_session:
            pos_session.ensure_one()
            if account_payment.company_id != pos_session.company_id:
                raise UserError(_('La sesión POS y el pago deben ser de la misma compañía.'))

        branch = (self.fiserv_branch or '').strip() or ''
        amount_cents = int(round(account_payment.amount * 100))
        if amount_cents <= 0:
            raise UserError(_('El importe del pago debe ser mayor que cero.'))

        currency_name = account_payment.currency_id.name
        currency_code = '840' if currency_name == 'USD' else '858'
        inv_num = self._fiserv_ref_invoice_account_payment(account_payment)
        pos_id = self._fiserv_resolve_pos_id_account_payment(account_payment)

        return {
            'PosID': pos_id,
            'SystemId': str(self.fiserv_system_id or ''),
            'Branch': branch,
            'ClientAppId': self.fiserv_client_app_id or '1',
            'UserId': str(self.env.user.id),
            'TransactionDateTimeyyyyMMddHHmmssSSS': self.get_formatted_timestamp(),
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
        }

    def _prepare_fiserv_itd_void_payload_for_account_payment(
        self, account_payment, pos_session, source_transaction
    ):
        """
        Payload ``processFinancialPurchaseVoidByTicket`` desde proveedor (sin POS).

        Args:
            account_payment (account.payment): Borrador «Enviar dinero».
            pos_session (pos.session): Vacío en contabilidad directa.
            source_transaction (payment.transaction): Cobro original.

        Returns:
            dict: Payload ITD.
        """
        self.ensure_one()
        account_payment.ensure_one()
        source_transaction.ensure_one()
        if pos_session:
            pos_session.ensure_one()
            if account_payment.company_id != pos_session.company_id:
                raise UserError(_('La sesión POS y el pago deben ser de la misma compañía.'))
        if source_transaction.company_id != account_payment.company_id:
            raise UserError(
                _('La transacción original debe ser de la misma compañía que el pago.')
            )

        ticket = (source_transaction.ticket_number or '').strip()
        if not ticket:
            raise UserError(
                _(
                    'La transacción de pago seleccionada no tiene número de ticket ITD; '
                    'no se puede anular por ticket.'
                )
            )

        branch = (self.fiserv_branch or '').strip() or ''
        acquirer = source_transaction.acquirer
        if acquirer is None or acquirer is False:
            acquirer = ''
        else:
            acquirer = str(acquirer).strip()
        pos_id = self._fiserv_resolve_pos_id_account_payment(account_payment)

        return {
            'PosID': pos_id,
            'SystemId': str(self.fiserv_system_id or ''),
            'Branch': branch,
            'ClientAppId': self.fiserv_client_app_id or '1',
            'UserId': str(self.env.user.id),
            'TransactionDateTimeyyyyMMddHHmmssSSS': self.get_formatted_timestamp(),
            'TicketNumber': ticket,
            'Acquirer': acquirer,
        }

    def _prepare_fiserv_itd_refund_payload(
        self, source_transaction, pos_id, amount_cents, user_id, invoice_number=None
    ):
        """
        Payload ``processFinancialPurchaseRefund`` genérico desde el proveedor.

        Fiserv acepta devolución total o parcial; `amount_cents` puede ser menor al
        monto de la transacción original. La fecha original se toma de ``create_date``
        de ``source_transaction`` en formato ``yyMMdd``.

        Args:
            source_transaction (payment.transaction): Cobro original Fiserv.
            pos_id (str): PosID del pinpad que procesa la devolución.
            amount_cents (int): Monto a devolver, en centavos.
            user_id (int): Usuario que inicia la operación.
            invoice_number (str|None): Si se pasa, sobreescribe el invoice_number de la tx.

        Returns:
            dict: Cuerpo JSON para ``/processFinancialPurchaseRefund``.
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

        inv = invoice_number
        if inv is None:
            inv = getattr(source_transaction, 'invoice_number', False) or ''
        inv = str(inv).strip()

        try:
            quotas = int(source_transaction.installments or 1)
            if quotas < 1:
                quotas = 1
        except (TypeError, ValueError):
            quotas = 1

        return {
            'PosID': pos_id,
            'SystemId': str(self.fiserv_system_id or ''),
            'Branch': (self.fiserv_branch or '').strip() or '',
            'ClientAppId': self.fiserv_client_app_id or '1',
            'UserId': str(user_id),
            'TransactionDateTimeyyyyMMddHHmmssSSS': self.get_formatted_timestamp(),
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
        }

    def _prepare_fiserv_itd_refund_payload_for_account_payment(
        self, account_payment, pos_session, source_transaction
    ):
        """
        Variante del payload de refund para cobro contable (sin POS).

        Resuelve el ``PosID`` desde ``fiserv.pos.terminal`` del pago y calcula el
        monto en centavos desde ``account_payment.amount``.
        """
        self.ensure_one()
        account_payment.ensure_one()
        source_transaction.ensure_one()
        if source_transaction.company_id != account_payment.company_id:
            raise UserError(
                _('La transacción original debe ser de la misma compañía que el pago.')
            )
        pos_id = self._fiserv_resolve_pos_id_account_payment(account_payment)
        amount_cents = int(round(account_payment.amount * 100))
        if amount_cents <= 0:
            raise UserError(_('El importe del pago debe ser mayor que cero.'))
        return self._prepare_fiserv_itd_refund_payload(
            source_transaction=source_transaction,
            pos_id=pos_id,
            amount_cents=amount_cents,
            user_id=self.env.user.id,
        )

    def _fiserv_store_transaction_error_contable(self, pos_data, itd_response, pos_session_id):
        """
        Registra en ``payment.transaction`` una respuesta ITD de error (inicio rechazado).

        Args:
            pos_data (dict): Payload enviado.
            itd_response (dict): JSON ITD.
            pos_session_id: False en contabilidad directa.
        """
        try:
            self.env['payment.transaction'].sudo().create_fiserv_transaction(
                pos_data=pos_data,
                itd_response=itd_response,
                pos_order=None,
                pos_payment=None,
            )
            _logger.info('Fiserv (proveedor): transacción de error almacenada')
        except Exception as err:
            _logger.error('Fiserv (proveedor): error al guardar transacción ITD: %s', str(err))

    def fiserv_process_financial_purchase_contable(self, data, pos_session_id, account_payment_id=None):
        """
        Igual que ``pos.payment.method.processFinancialPurchase`` pero usando credenciales del proveedor.

        Usado desde ``account.payment`` cuando no hay ``pos.payment.method`` en el diario.

        Args:
            data (dict): Payload ITD.
            pos_session_id: False desde contabilidad.
            account_payment_id (int|None): ID del pago contable.

        Returns:
            dict: Respuesta inicial ITD.
        """
        from .fiserv_utils import fiserv_itd_background_worker_account_payment, fiserv_itd_http_post

        self.ensure_one()
        _logger.info('Fiserv proveedor processFinancialPurchase (contable) %s', pprint.pformat(data))

        base_url_endpoint, response_json = fiserv_itd_http_post(
            (self.sudo().fiserv_url_webservice or '').rstrip('/'),
            '/processFinancialPurchase',
            data,
            'processFinancialPurchase',
            extra_999_pos_warning=True,
        )

        if response_json['ResponseCode'] != '0':
            self._fiserv_store_transaction_error_contable(
                data, response_json, pos_session_id or False
            )

        if response_json['ResponseCode'] == '0':
            transaction_id = response_json['TransactionId']
            bus_channel_name, id_config = None, 0
            store_sid = pos_session_id if pos_session_id else False
            run_uid = self.env.uid if account_payment_id else None
            threading.Thread(
                target=fiserv_itd_background_worker_account_payment,
                args=(
                    self.pool,
                    self.id,
                    run_uid,
                    data,
                    bus_channel_name,
                    id_config,
                    transaction_id,
                    base_url_endpoint,
                    store_sid,
                    account_payment_id,
                ),
            ).start()

        return response_json

    def fiserv_process_financial_purchase_void_contable(self, data, pos_session_id, account_payment_id=None):
        """
        Anulación por ticket desde proveedor (contabilidad sin POS).

        Si ITD rechaza el void con RC 109/110 (ticket fuera del lote actual del
        pinpad: hubo cierre de lote entre la venta y el intento de anular), se hace
        fallback automático a ``processFinancialPurchaseRefund`` con el payload
        construido a partir de la transacción original. El frontend recibe la
        respuesta final como si el usuario hubiera pedido refund directamente.
        """
        from .fiserv_utils import (
            FISERV_ITD_RC_VOID_SHOULD_REFUND,
            fiserv_itd_background_worker_account_payment,
            fiserv_itd_http_post,
        )

        self.ensure_one()
        _logger.info('Fiserv proveedor processFinancialPurchaseVoidByTicket (contable) %s', pprint.pformat(data))

        base_url_endpoint, response_json = fiserv_itd_http_post(
            (self.sudo().fiserv_url_webservice or '').rstrip('/'),
            '/processFinancialPurchaseVoidByTicket',
            data,
            'processFinancialPurchaseVoidByTicket',
            extra_999_pos_warning=False,
        )

        rc = str(response_json.get('ResponseCode', '999')).strip()

        if rc in FISERV_ITD_RC_VOID_SHOULD_REFUND and account_payment_id:
            _logger.info(
                'Fiserv void rechazó RC=%s (ticket fuera del lote actual). '
                'Fallback automático a processFinancialPurchaseRefund. account_payment=%s',
                rc, account_payment_id,
            )
            data, response_json = self._fiserv_switch_void_to_refund_contable(
                account_payment_id, data,
            )
            rc = str(response_json.get('ResponseCode', '999')).strip()

        if rc != '0':
            self._fiserv_store_transaction_error_contable(
                data, response_json, pos_session_id or False
            )
            return response_json

        transaction_id = response_json['TransactionId']
        bus_channel_name, id_config = None, 0
        store_sid = pos_session_id if pos_session_id else False
        run_uid = self.env.uid if account_payment_id else None
        threading.Thread(
            target=fiserv_itd_background_worker_account_payment,
            args=(
                self.pool,
                self.id,
                run_uid,
                data,
                bus_channel_name,
                id_config,
                transaction_id,
                base_url_endpoint,
                store_sid,
                account_payment_id,
            ),
        ).start()

        return response_json

    def _fiserv_switch_void_to_refund_contable(self, account_payment_id, void_data):
        """
        Construye y envía ``processFinancialPurchaseRefund`` tras un void RC=109/110.

        Usa el ``fiserv_original_transaction_id`` del pago y el mismo PosID que el
        void original (tomado de ``void_data['PosID']``).

        Returns:
            tuple: (refund_data, response_json) listos para seguir el flujo normal.
        """
        from .fiserv_utils import fiserv_itd_http_post

        self.ensure_one()
        pay = self.env['account.payment'].sudo().browse(account_payment_id)
        if not pay.exists():
            raise UserError(_('Pago contable no existe; no se puede iniciar devolución.'))
        source_tx = pay.fiserv_original_transaction_id
        if not source_tx:
            raise UserError(
                _('Falta la transacción Fiserv original en el pago; no se puede hacer devolución.')
            )
        refund_data = self._prepare_fiserv_itd_refund_payload(
            source_transaction=source_tx,
            pos_id=str(void_data.get('PosID', '')),
            amount_cents=int(round(pay.amount * 100)),
            user_id=self.env.user.id,
        )
        _logger.info(
            'Fiserv proveedor processFinancialPurchaseRefund (contable) %s',
            pprint.pformat(refund_data),
        )
        _base, response_json = fiserv_itd_http_post(
            (self.sudo().fiserv_url_webservice or '').rstrip('/'),
            '/processFinancialPurchaseRefund',
            refund_data,
            'processFinancialPurchaseRefund',
            extra_999_pos_warning=False,
        )
        return refund_data, response_json
