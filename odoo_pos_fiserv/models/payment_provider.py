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
        # --- Import diferido: evita dependencia circular al cargar modelos ---
        from .pos_payment_method import _fiserv_normalize_itd_http_response

        # --- POST al servicio Query (el bucle actualiza TransactionDateTime en ``data``) ---
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
        from .pos_payment_method import _fiserv_normalize_itd_http_response

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

        Args:
            account_payment (account.payment): Pago contable.

        Returns:
            str: Sufijo numérico para ITD.
        """
        pay = account_payment
        if 'reconciled_invoice_ids' in pay._fields and pay.reconciled_invoice_ids:
            inv = pay.reconciled_invoice_ids.sorted('id', reverse=True)[:1]
            if inv:
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
        from .pos_payment_method import fiserv_itd_background_worker_account_payment, fiserv_itd_http_post

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

        Args:
            data (dict): Payload void ITD.
            pos_session_id: False desde contabilidad.
            account_payment_id (int|None): ID del pago contable.

        Returns:
            dict: Respuesta inicial ITD.
        """
        from .pos_payment_method import fiserv_itd_background_worker_account_payment, fiserv_itd_http_post

        self.ensure_one()
        _logger.info('Fiserv proveedor processFinancialPurchaseVoidByTicket (contable) %s', pprint.pformat(data))

        base_url_endpoint, response_json = fiserv_itd_http_post(
            (self.sudo().fiserv_url_webservice or '').rstrip('/'),
            '/processFinancialPurchaseVoidByTicket',
            data,
            'processFinancialPurchaseVoidByTicket',
            extra_999_pos_warning=False,
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
