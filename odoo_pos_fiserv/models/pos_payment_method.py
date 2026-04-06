import threading
import pprint
import logging
import requests

from time import sleep
from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)

# Mensajes ITD alineados con la tabla de códigos de respuesta del servicio (processFinancial*, cancel, reverse).
FISERV_ITD_RESPONSE_CODE_MSG = {
    '0': 'Resultado OK',
    '10': 'Aguardando por operación en el pinpad.',
    '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
    '12': 'Pinpad consultó datos (se pasó la tarjeta o Poleo Automático).',
    '100': 'Número de pinpad inválido',
    '101': 'Número de sucursal inválido',
    '102': 'Número de caja inválido',
    '103': 'Fecha de la transacción inválida',
    '104': 'Monto no válido',
    '105': 'Cantidad de cuotas inválidas',
    '106': 'Número de plan inválido',
    '107': 'Número de factura inválido',
    '108': 'Moneda ingresada no válida',
    '109': 'Número de ticket inválido.',
    '110': 'No existe transacción.',
    '111': 'Transacción finalizada.',
    '112': 'Identificador de sistema inválido.',
    '113': 'Se debe consultar por la transacción',
    '999': 'Error no determinado.',
    '-100': 'Formato en campo/s incorrecta; Faltan campos obligatorios',
}


def _fiserv_normalize_itd_http_response(response_json):
    """
    Normaliza el JSON devuelto por ITD: ResponseCode y TransactionId suelen venir como int;
    Odoo y el POS comparan contra strings. Evita KeyError si aparece un código nuevo.
    """
    if not isinstance(response_json, dict):
        return response_json
    rc = response_json.get('ResponseCode')
    response_json['ResponseCode'] = str(rc).strip() if rc is not None else '999'
    tid = response_json.get('TransactionId')
    if tid is not None:
        response_json['TransactionId'] = str(tid).strip()
    stid = response_json.get('STransactionId')
    if stid is not None:
        response_json['STransactionId'] = str(stid).strip()
    code = response_json['ResponseCode']
    response_json['msg'] = FISERV_ITD_RESPONSE_CODE_MSG.get(
        code,
        'Respuesta ITD (código %s)' % code,
    )
    return response_json


def _fiserv_card_data_ready_for_confirm(query_result):
    """
    Indica si la consulta ITD trae BIN/adquirente/emisor útiles para confirmar la compra.

    ITD suele devolver Acquirer/Issuer numéricos distintos de 0 cuando la tarjeta ya fue leída
    (ResponseCode 12). Sin esto no se debe llamar a processConfirmFinancialPurchase.
    """
    try:
        acq = int(str(query_result.get('Acquirer', 0)).strip() or 0)
        iss = int(str(query_result.get('Issuer', 0)).strip() or 0)
    except (TypeError, ValueError):
        return False
    return acq != 0 and iss != 0


def _fiserv_resolve_quota_for_confirm(purchase_data, query_result):
    """
    Cuotas finales para confirm: prioriza lo devuelto por Query (Quota/Quotas), luego el cobro inicial.
    """
    for key in ('Quota', 'Quotas'):
        val = query_result.get(key)
        if val is not None and val != '':
            try:
                n = int(str(val).strip())
                if n >= 1:
                    return n
            except (TypeError, ValueError):
                continue
    for key in ('Installments', 'Quotas'):
        val = purchase_data.get(key)
        if val is not None and val != '':
            try:
                n = int(str(val).strip())
                if n >= 1:
                    return n
            except (TypeError, ValueError):
                continue
    return 1


def _fiserv_build_confirm_financial_purchase_payload(
    original_purchase_data,
    query_result,
    transaction_id,
    payment_method,
):
    """
    Arma el cuerpo de processConfirmFinancialPurchase (POSLink / ITD) tras RC=12.

    Debe alinearse con el payload inicial (montos en centavos como string) y con los datos
    de tarjeta devueltos por processFinancialPurchaseQuery.
    """
    quota_value = _fiserv_resolve_quota_for_confirm(original_purchase_data, query_result)
    try:
        tax_refund = int(original_purchase_data.get('TaxRefund', 0))
    except (TypeError, ValueError):
        tax_refund = 0
    plan_raw = original_purchase_data.get('Plan', 0)
    try:
        plan_val = int(plan_raw)
    except (TypeError, ValueError):
        plan_val = 0
    return {
        'PosID': original_purchase_data['PosID'],
        'SystemId': original_purchase_data['SystemId'],
        'Branch': original_purchase_data['Branch'],
        'ClientAppId': original_purchase_data['ClientAppId'],
        'UserId': str(original_purchase_data['UserId']),
        'TransactionDateTimeyyyyMMddHHmmssSSS': payment_method.get_formatted_timestamp(),
        'TransactionId': str(transaction_id).strip(),
        'Amount': str(original_purchase_data.get('Amount', '0')),
        'Quotas': quota_value,
        'Plan': plan_val,
        'Currency': str(original_purchase_data.get('Currency', '858')),
        'TaxRefund': tax_refund,
        'TaxableAmount': str(original_purchase_data.get('TaxableAmount', '0')),
        'InvoiceAmount': str(original_purchase_data.get('InvoiceAmount', '0')),
        'InvoiceNumber': str(original_purchase_data.get('InvoiceNumber', '1')),
        'TaxAmount': '0',
        'TipAmount': '0',
        'CardAccountType': '0',
        'Acquirer': query_result.get('Acquirer', ''),
        'Issuer': query_result.get('Issuer', ''),
        'CardNumber': query_result.get('CardNumber', ''),
    }


def _fiserv_http_post_confirm_financial_purchase(base_url_endpoint, confirm_data):
    """
    POST a processConfirmFinancialPurchase; normaliza ResponseCode/msg como el resto de ITD.
    """
    endpoint = (base_url_endpoint or '').rstrip('/') + '/processConfirmFinancialPurchase'
    req = requests.post(
        endpoint,
        json=confirm_data,
        headers={'Content-Type': 'application/json'},
        timeout=30,
    )
    response_json = req.json()
    _fiserv_normalize_itd_http_response(response_json)
    _logger.info('processConfirmFinancialPurchase Response:\n%s', pprint.pformat(response_json))
    return response_json


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super(PosPaymentMethod, self)._get_payment_terminal_selection() + [('fiserv', 'Fiserv ITD')]

    def get_formatted_timestamp(self):
        now = datetime.now()
        return now.strftime('%Y%m%d%H%M%S') + f'{int(now.microsecond / 1000):03d}'

    url_webservice = fields.Char('URL servicio web')
    codigo_sistema = fields.Char('Código Sistema (SystemId)')
    codigo_terminal = fields.Char('Código Terminal (PosID)')
    client_app_id = fields.Char('Client APP ID', default='1')
    codigo_sucursal = fields.Integer('Código Sucursal')
    fiserv_branch = fields.Char(
        string='Branch ITD',
        help='Sucursal Fiserv (texto ITD). Si está vacío, en el POS se envía el código sucursal numérico como texto.',
    )
    fiserv_provider_id = fields.Many2one(
        comodel_name='payment.provider',
        string='Proveedor Fiserv',
        domain="[('code', '=', 'fiserv')]",
    )
    fiserv_terminal_id = fields.Many2one(
        comodel_name='fiserv.pos.terminal',
        string='Terminal Fiserv (PosID)',
        domain="[('payment_provider_id', '=', fiserv_provider_id)]",
    )
    fiserv_provider_is_multiple = fields.Boolean(
        string='Proveedor con múltiples POS',
        related='fiserv_provider_id.fiserv_is_multiple',
        readonly=True,
    )

    @api.onchange('fiserv_provider_id', 'fiserv_terminal_id')
    def _onchange_fiserv_provider_terminal(self):
        """
        Sincroniza URL, SystemId, Branch y ClientApp desde el proveedor Fiserv.

        Con múltiples POS, el PosID se toma del terminal seleccionado.
        """
        for rec in self:
            if rec.use_payment_terminal != 'fiserv':
                continue
            prov = rec.fiserv_provider_id
            if not prov or prov.code != 'fiserv':
                continue
            rec.url_webservice = prov.fiserv_url_webservice
            rec.codigo_sistema = prov.fiserv_system_id
            rec.client_app_id = prov.fiserv_client_app_id or '1'
            if prov.fiserv_branch:
                rec.fiserv_branch = prov.fiserv_branch
            if prov.fiserv_is_multiple and rec.fiserv_terminal_id:
                rec.codigo_terminal = rec.fiserv_terminal_id.pos_id
            elif not prov.fiserv_is_multiple:
                rec.fiserv_terminal_id = False

    def enviar_pago(self, data, pos_session_id, has_refunded_line):
        self.ensure_one()
        if not has_refunded_line:
            return self.processFinancialPurchase(data, pos_session_id)

        return self.processFinancialPurchaseVoidByTicket(data, pos_session_id)

    def _fiserv_bus_channel_and_config(self, pos_session_id, account_payment_id=None):
        """
        Nombre de canal bus + id_config para reflejar estado en el front del TPV.

        Cobro originado en account.payment: siempre sin bus (ITD directo desde contabilidad).
        Flujo TPV (pos.payment): exige sesión abierta cuando se notifica al cliente.
        """
        self.ensure_one()
        # --- Pago contable estándar: no hay canal bus ni config POS ---
        if account_payment_id:
            return None, 0
        if not pos_session_id:
            raise UserError(
                _('Se requiere una sesión de caja abierta para notificar el TPV en este cobro Fiserv.')
            )
        pos_session_sudo = self.env['pos.session'].sudo().browse(pos_session_id)
        if not pos_session_sudo.exists():
            raise UserError(_('La sesión POS indicada no existe.'))
        return pos_session_sudo._get_bus_channel_name(), pos_session_sudo.config_id.id

    def _fiserv_http_post_financial_purchase(self, data):
        """
        Envía processFinancialPurchase al endpoint ITD y devuelve URL base + JSON normalizado.

        Args:
            data (dict): Cuerpo JSON para ITD.

        Returns:
            tuple: (base_url_endpoint, response_json)
        """
        self.ensure_one()
        base_url_endpoint = (self.sudo().url_webservice or '').rstrip('/')
        endpoint = base_url_endpoint + '/processFinancialPurchase'
        req = requests.post(
            endpoint,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=30,
        )
        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        _logger.info('processFinancialPurchase Response:\n%s', pprint.pformat(response_json))
        return base_url_endpoint, response_json

    def _fiserv_http_post_void_by_ticket(self, data):
        """
        POST a processFinancialPurchaseVoidByTicket (anulación / devolución por ticket ITD).

        Args:
            data (dict): Payload mínimo (cabecera ITD + TicketNumber + Acquirer; opcional factura).

        Returns:
            tuple: (base_url_endpoint, response_json)
        """
        self.ensure_one()
        base_url_endpoint = (self.sudo().url_webservice or '').rstrip('/')
        endpoint = base_url_endpoint + '/processFinancialPurchaseVoidByTicket'
        req = requests.post(
            endpoint,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=30,
        )
        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        _logger.info('processFinancialPurchaseVoidByTicket Response:\n%s', pprint.pformat(response_json))
        return base_url_endpoint, response_json

    @api.model
    def fiserv_run_purchase_query_loop(
        self,
        payment_method,
        query_data,
        base_url_endpoint,
        transaction_id,
        pos_session_id,
        original_purchase_data=None,
    ):
        """
        Consulta processFinancialPurchaseQuery en bucle hasta respuesta final (mismo criterio que el hilo POS).

        Si el cobro inicial llevó NeedToReadCard=True (TPV y account.payment), ITD pasa por RC 10/12
        hasta leer la tarjeta y exige un único POST processConfirmFinancialPurchase para enviar al host;
        sin eso el pinpad queda en «Enviando al host» y Query devuelve 12 en bucle.

        Args:
            payment_method (pos.payment.method): Método Fiserv (terminal ITD).
            query_data (dict): Payload de consulta (TransactionId, PosID, etc.).
            base_url_endpoint (str): URL base ITD.
            transaction_id: ID ITD (referencia de logs).
            pos_session_id (int): Sesión POS (para reversos coherentes).
            original_purchase_data (dict|None): Payload completo de processFinancialPurchase (montos, NeedToReadCard).

        Returns:
            dict: Última respuesta ITD del bucle.
        """
        payment_method.ensure_one()
        result = {}
        # --- Tras RC=12 solo se confirma una vez; ITD continúa el flujo hacia aprobación o error ---
        confirm_after_card_read_done = False
        max_iterations = 900
        iteration = 0
        while True:
            iteration += 1
            if iteration > max_iterations:
                _logger.error(
                    'Fiserv query loop: límite de iteraciones (%s) alcanzado (tx=%s)',
                    max_iterations,
                    transaction_id,
                )
                result = {
                    'ResponseCode': '999',
                    'msg': _(
                        'Tiempo máximo de espera en consultas ITD agotado. Revise el pinpad o reintente.'
                    ),
                    'TransactionId': transaction_id,
                }
                break
            sleep(4)
            # --- ITD/OCA: cada consulta lleva timestamp nuevo; uno fijo puede dejar RC=10 colgado ---
            query_data['TransactionDateTimeyyyyMMddHHmmssSSS'] = (
                payment_method.get_formatted_timestamp()
            )
            _logger.info('>>>Intento Fiserv query>>>')
            try:
                result = payment_method.processFinancialPurchaseQuery(query_data, base_url_endpoint)
                _logger.info('Result: %s', pprint.pformat(result))

                response_code = str(result.get('ResponseCode', '999')).strip()
                rt_raw = result.get('RemainingExpirationTime', False)
                rt_num = None
                if rt_raw is not False and rt_raw is not None and rt_raw != '':
                    try:
                        rt_num = float(rt_raw)
                    except (TypeError, ValueError):
                        rt_num = None

                # --- ITD: tras leer tarjeta (12) hay que confirmar montos/datos para «Enviar al host» ---
                need_read_card = bool(
                    original_purchase_data
                    and original_purchase_data.get('NeedToReadCard')
                )
                if (
                    need_read_card
                    and not confirm_after_card_read_done
                    and response_code == '12'
                    and _fiserv_card_data_ready_for_confirm(result)
                ):
                    confirm_payload = _fiserv_build_confirm_financial_purchase_payload(
                        original_purchase_data,
                        result,
                        transaction_id,
                        payment_method,
                    )
                    _logger.info(
                        'Fiserv ITD: processConfirmFinancialPurchase tras RC=12 | tx=%s',
                        transaction_id,
                    )
                    try:
                        conf = _fiserv_http_post_confirm_financial_purchase(
                            base_url_endpoint,
                            confirm_payload,
                        )
                        confirm_after_card_read_done = True
                        crc = str(conf.get('ResponseCode', '999')).strip()
                        if crc in ('999', '-100'):
                            result = conf
                            break
                    except Exception as conf_err:
                        _logger.exception(
                            'Fiserv: fallo HTTP/JSON en processConfirmFinancialPurchase: %s',
                            conf_err,
                        )
                        result = {
                            'ResponseCode': '999',
                            'msg': str(conf_err),
                            'TransactionId': transaction_id,
                        }
                        break

                if response_code not in ['10', '12']:
                    break

                if response_code in ['10', '12'] and rt_num is not None and rt_num <= 0:
                    _logger.warning(
                        'Tiempo de transacción expirado para %s. Reversión...',
                        transaction_id,
                    )
                    reverse_result = payment_method.processFinancialReverse(
                        query_data, base_url_endpoint
                    )
                    _logger.info('Resultado de reversión: %s', pprint.pformat(reverse_result))
                    result = {
                        'ResponseCode': '11',
                        'msg': 'Tiempo de transacción excedido, envíe datos nuevamente.',
                        'TransactionId': transaction_id,
                        'RemainingExpirationTime': 0.0,
                        'timeout_error': True,
                        'reverse_processed': True,
                    }
                    if reverse_result.get('ResponseCode') == '0':
                        result['reverse_success'] = True
                        result['reverse_msg'] = 'Reversión procesada exitosamente'
                    else:
                        result['reverse_success'] = False
                        result['reverse_msg'] = reverse_result.get('msg', 'Error en reversión')
                    break

            except Exception as e:
                _logger.error('Error en bucle de consulta Fiserv: %s', str(e))
                result = {
                    'ResponseCode': '999',
                    'msg': 'Error no determinado.',
                    'TransactionId': transaction_id,
                    'error': str(e),
                }
                break
            _logger.info('>>>FIN Intento Fiserv query>>>')

        return result

    def _fiserv_account_payment_invoice_reference(self, account_payment):
        """
        Referencia obligatoria ITD para «información de factura»:
        si el pago tiene facturas reconciliadas, se usa su numeración; si no, el id del pago.

        Args:
            account_payment (account.payment): Pago contable (entrada o salida).

        Returns:
            str: Hasta 7 caracteres alineados al uso en TPV (sufijo numérico).
        """
        pay = account_payment
        # --- reconciled_invoice_ids existe en account.payment estándar (cliente/proveedor) ---
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

    def _fiserv_resolve_pos_id_for_account_payment(self, account_payment):
        """
        Devuelve el PosID ITD a usar desde contabilidad.

        Con proveedor multi-POS se prioriza el terminal elegido en el pago; si no hay
        registro pero el método tiene código, se usa ese código. Con un solo POS se
        usa el código configurado en el método.

        Args:
            account_payment (account.payment): Pago contable en borrador.

        Returns:
            str: PosID no vacío o lanza UserError si falta configuración.
        """
        self.ensure_one()
        account_payment.ensure_one()
        if self.use_payment_terminal != 'fiserv':
            raise UserError(_('El método de pago POS debe ser Fiserv ITD.'))

        prov = self.fiserv_provider_id
        term = account_payment.fiserv_terminal_id

        # --- Multi-POS: terminal explícito o respaldo al código del método ---
        if prov and prov.fiserv_is_multiple:
            if term:
                if term.payment_provider_id != prov:
                    raise UserError(
                        _(
                            'El terminal «%(t)s» no pertenece al proveedor Fiserv del método «%(m)s».'
                        )
                        % {
                            't': term.display_name,
                            'm': self.display_name,
                        }
                    )
                pos_id = (term.pos_id or '').strip()
                if pos_id:
                    return pos_id
            code = (self.codigo_terminal or '').strip()
            if code:
                return code
            raise UserError(
                _(
                    'Configure un terminal Fiserv (PosID) en el pago o el código terminal en el método «%s».'
                )
                % self.display_name
            )

        # --- Un solo POS: siempre el código del método ---
        code = (self.codigo_terminal or '').strip()
        if not code:
            raise UserError(
                _('Falta el código terminal (PosID) en el método de pago «%s».')
                % self.display_name
            )
        return code

    def _prepare_fiserv_itd_payload_for_account_payment(self, account_payment, pos_session):
        """
        Arma el dict processFinancialPurchase (montos en centavos, moneda ITD).

        Args:
            account_payment (account.payment): Borrador de pago contable.
            pos_session (pos.session): Vacío si el cobro es sólo desde contabilidad; si se pasara
                sesión, se valida misma compañía (compatibilidad).

        Returns:
            dict: Payload para processFinancialPurchase.
        """
        self.ensure_one()
        account_payment.ensure_one()
        if pos_session:
            pos_session.ensure_one()
            if account_payment.company_id != pos_session.company_id:
                raise UserError(
                    _('La sesión POS y el pago deben ser de la misma compañía.')
                )

        branch = self.fiserv_branch
        if (branch is None or branch is False or str(branch).strip() == '') and self.codigo_sucursal is not None:
            branch = str(self.codigo_sucursal)

        amount_cents = int(round(account_payment.amount * 100))
        if amount_cents <= 0:
            raise UserError(_('El importe del pago debe ser mayor que cero.'))

        currency_name = account_payment.currency_id.name
        if currency_name == 'USD':
            currency_code = '840'
        else:
            currency_code = '858'

        inv_num = self._fiserv_account_payment_invoice_reference(account_payment)

        # --- PosID: terminal explícito en pago contable (multi-POS) o código del método ---
        pos_id = self._fiserv_resolve_pos_id_for_account_payment(account_payment)

        return {
            'PosID': pos_id,
            'SystemId': self.codigo_sistema,
            'Branch': branch or '',
            'ClientAppId': self.client_app_id or '1',
            'UserId': str(self.env.user.id),
            'TransactionDateTimeyyyyMMddHHmmssSSS': self.get_formatted_timestamp(),
            'Amount': str(amount_cents),
            'Quotas': 1,
            'Plan': 0,
            'Currency': currency_code,
            'TaxRefund': 0,
            'TaxableAmount': str(amount_cents),
            'InvoiceAmount': str(amount_cents),
            'InvoiceNumber': inv_num,
            'Installments': 1,
            'TicketNumber': '',
            'NeedToReadCard': True,
        }

    def _prepare_fiserv_itd_void_payload_for_account_payment(self, account_payment, pos_session, source_transaction):
        """
        Payload processFinancialPurchaseVoidByTicket (devolución / enviar dinero).

        Mismo cuerpo que el TPV en devolución: cabecera ITD + TicketNumber + Acquirer
        obtenidos de la transacción Fiserv original.

        Args:
            account_payment (account.payment): Borrador «Enviar dinero».
            pos_session (pos.session): Vacío para flujo contable directo; opcional validación compañía.
            source_transaction (payment.transaction): Cobro Fiserv original a anular por ticket.

        Returns:
            dict: Payload para processFinancialPurchaseVoidByTicket.
        """
        self.ensure_one()
        account_payment.ensure_one()
        source_transaction.ensure_one()
        if pos_session:
            pos_session.ensure_one()
            if account_payment.company_id != pos_session.company_id:
                raise UserError(
                    _('La sesión POS y el pago deben ser de la misma compañía.')
                )
        if source_transaction.company_id != account_payment.company_id:
            raise UserError(
                _('La transacción original debe ser de la misma compañía que el pago.')
            )

        ticket = (source_transaction.ticket_number or '').strip()
        if not ticket:
            raise UserError(
                _('La transacción de pago seleccionada no tiene número de ticket ITD; no se puede anular por ticket.')
            )

        branch = self.fiserv_branch
        if (branch is None or branch is False or str(branch).strip() == '') and self.codigo_sucursal is not None:
            branch = str(self.codigo_sucursal)

        acquirer = source_transaction.acquirer
        if acquirer is None or acquirer is False:
            acquirer = ''
        else:
            acquirer = str(acquirer).strip()

        # --- PosID alineado con el cobro / selección en account.payment ---
        pos_id = self._fiserv_resolve_pos_id_for_account_payment(account_payment)

        # --- Mismo cuerpo mínimo que el TPV en devolución (processFinancialPurchaseVoidByTicket) ---
        return {
            'PosID': pos_id,
            'SystemId': self.codigo_sistema,
            'Branch': branch or '',
            'ClientAppId': self.client_app_id or '1',
            'UserId': str(self.env.user.id),
            'TransactionDateTimeyyyyMMddHHmmssSSS': self.get_formatted_timestamp(),
            'TicketNumber': ticket,
            'Acquirer': acquirer,
        }

    def processFinancialPurchase(self, data, pos_session_id, account_payment_id=None):
        """
        Envía processFinancialPurchase a ITD y delega el bucle de consultas en un hilo (igual que el TPV).

        Args:
            data (dict): Payload ITD.
            pos_session_id (int): Sesión POS (canal bus / config; en backend se resuelve sola).
            account_payment_id (int|None): Si viene de account.payment, al terminar el hilo se enlaza
                la transacción y se contabiliza el pago si ITD queda aprobado.

        Returns:
            dict: Respuesta inicial de ITD (ResponseCode 0 = operación lanzada al pinpad).
        """
        self.ensure_one()
        _logger.info('Metodo processFinancialPurchase %s', pprint.pformat(data))
        
        # Log detallado de los campos enviados
        _logger.info('Fiserv Data Fields Check:')
        _logger.info('  PosID: %s', data.get('PosID'))
        _logger.info('  SystemId: %s', data.get('SystemId'))
        _logger.info('  Branch: %s', data.get('Branch'))
        _logger.info('  ClientAppId: %s', data.get('ClientAppId'))
        _logger.info('  UserId: %s', data.get('UserId'))
        _logger.info('  Amount: %s', data.get('Amount'))
        _logger.info('  Currency: %s', data.get('Currency'))
        _logger.info('  InvoiceNumber: %s', data.get('InvoiceNumber'))
        _logger.info('  TransactionDateTimeyyyyMMddHHmmssSSS: %s', data.get('TransactionDateTimeyyyyMMddHHmmssSSS'))

        base_url_endpoint, response_json = self._fiserv_http_post_financial_purchase(data)

        # Almacenar la transacción en payment.transaction SOLO cuando recibimos respuesta del POS
        # PERO solo si la respuesta es exitosa y tenemos información completa
        if response_json['ResponseCode'] == '0':
            # Solo almacenar la transacción cuando tengamos información completa
            # La información completa llega después del procesamiento en segundo plano
            pass
        else:
            # Para respuestas de error, almacenar inmediatamente
            self._store_fiserv_transaction(data, response_json, pos_session_id or False)

        if response_json['ResponseCode'] == '0':
            transaction_id = response_json['TransactionId']
            bus_channel_name, id_config = self._fiserv_bus_channel_and_config(
                pos_session_id, account_payment_id=account_payment_id
            )
            store_sid = pos_session_id if pos_session_id else False
            threading.Thread(
                target=self._procesar_en_segundo_plano,
                args=(
                    data,
                    bus_channel_name,
                    id_config,
                    transaction_id,
                    base_url_endpoint,
                    store_sid,
                    account_payment_id,
                    self.env.uid if account_payment_id else None,
                ),
            ).start()

        return response_json

    def _store_fiserv_transaction(self, pos_data, itd_response, pos_session_id):
        """
        Almacena la información de la transacción Fiserv en payment.transaction
        SOLO cuando recibimos respuesta del POS
        
        Args:
            pos_data (dict): Datos enviados al POS
            itd_response (dict): Respuesta recibida del POS
            pos_session_id (int): ID de la sesión POS
        """
        try:
            # Buscar el pedido POS relacionado
            pos_order = self._find_related_pos_order_by_transaction_with_data(itd_response.get('TransactionId', ''), pos_session_id, pos_data)
            pos_payment = self._find_related_pos_payment(pos_data, pos_session_id)
            
            # Crear la transacción en payment.transaction
            self.env['payment.transaction'].sudo().create_fiserv_transaction(
                pos_data=pos_data,
                itd_response=itd_response,
                pos_order=pos_order,
                pos_payment=pos_payment
            )
            
            _logger.info('Transacción Fiserv almacenada exitosamente después de recibir respuesta del POS')
            
        except Exception as e:
            _logger.error('Error al almacenar transacción Fiserv: %s', str(e))

    def _find_related_pos_order_by_transaction_with_data(self, transaction_id, pos_session_id, pos_data):
        """
        Busca el pedido POS relacionado con una transacción usando los datos del POS
        
        Args:
            transaction_id (str): ID de la transacción Fiserv
            pos_session_id (int): ID de la sesión POS
            pos_data (dict): Datos enviados al POS
            
        Returns:
            pos.order: Pedido POS encontrado o None
        """
        try:
            # Intentar encontrar el pedido por el número de factura que viene en los datos del POS
            invoice_number = pos_data.get('InvoiceNumber')
            if invoice_number:
                _logger.info('Buscando pedido POS por InvoiceNumber: %s en sesión: %s', invoice_number, pos_session_id)
                
                # Buscar por tracking_number del pedido
                pos_orders = self.env['pos.order'].search([
                    ('session_id', '=', pos_session_id)
                ])
                
                for order in pos_orders:
                    if order.tracking_number:
                        # Formatear el tracking_number para comparar (máximo 7 caracteres)
                        order_tracking = str(order.tracking_number)
                        if len(order_tracking) > 7:
                            order_tracking = order_tracking[-7:]
                        else:
                            order_tracking = order_tracking.zfill(7)
                        
                        if order_tracking == invoice_number:
                            _logger.info('Pedido POS encontrado por tracking_number: %s (InvoiceNumber: %s)', order.name, invoice_number)
                            return order

                inv_norm = str(invoice_number).strip()
                for order in pos_orders:
                    oid_suffix = str(order.id)[-7:].zfill(7)
                    if oid_suffix == inv_norm:
                        _logger.info(
                            'Pedido POS encontrado por id (sufijo 7 dígitos): %s (InvoiceNumber: %s)',
                            order.name,
                            invoice_number,
                        )
                        return order

                try:
                    if inv_norm.isdigit() and str(int(inv_norm)) == inv_norm:
                        order_id = int(inv_norm)
                        _logger.info('Intentando buscar por ID del pedido: %s', order_id)
                        pos_order = self.env['pos.order'].search(
                            [
                                ('id', '=', order_id),
                                ('session_id', '=', pos_session_id),
                            ],
                            limit=1,
                        )
                        if pos_order:
                            _logger.info(
                                'Pedido POS encontrado por ID: %s (InvoiceNumber: %s)',
                                pos_order.name,
                                invoice_number,
                            )
                            return pos_order
                        _logger.warning(
                            'No se encontró pedido con ID %s en sesión %s',
                            order_id,
                            pos_session_id,
                        )
                except (ValueError, TypeError) as e:
                    _logger.warning('Error al convertir InvoiceNumber a ID: %s', str(e))
            
            # Si no se encuentra por InvoiceNumber, NO usar más el fallback de
            # \"último pedido de la sesión\" porque puede asociar la transacción
            # a la orden anterior en lugar de la orden actual.
            #
            # En su lugar, dejamos la transacción sin pos_order_id y delegamos
            # la asociación final a pos.order._associate_fiserv_transactions()
            # cuando se cree y registre efectivamente la orden.
            _logger.info(
                'No se encontró pedido POS por InvoiceNumber para transacción %s en sesión %s. '
                'Se deja sin pedido asociado y se delega asociación a pos.order._associate_fiserv_transactions.',
                transaction_id,
                pos_session_id,
            )
            return self.env['pos.order']
            
        except Exception as e:
            _logger.error('Error al buscar pedido POS relacionado: %s', str(e))
            return None

    def _find_related_pos_payment(self, pos_data, pos_session_id):
        """
        Busca el pago POS relacionado con la transacción
        
        Args:
            pos_data (dict): Datos de la transacción
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.payment: Pago POS encontrado o None
        """
        try:
            # Obtener el monto del POS (está en centavos)
            pos_amount = pos_data.get('Amount', 0.0)
            if isinstance(pos_amount, str):
                try:
                    pos_amount = float(pos_amount)
                except (ValueError, TypeError):
                    pos_amount = 0.0
            
            # Convertir el monto del POS desde centavos a la unidad correcta
            pos_amount_corrected = pos_amount / 100.0 if pos_amount > 0 else 0.0
            
            # Log para debuggear la búsqueda del pago POS
            _logger.info('Fiserv Payment Search Debug - POS Amount: %s, Corrected: %s, Session: %s', 
                        pos_amount, pos_amount_corrected, pos_session_id)
            
            if pos_amount_corrected > 0:
                # Buscar pagos recientes en la sesión que coincidan con el monto corregido
                pos_payment = self.env['pos.payment'].search([
                    ('session_id', '=', pos_session_id),
                    ('amount', '=', pos_amount_corrected),
                    ('payment_method_id', '=', self.id)
                ], order='id desc', limit=1)
                
                if not pos_payment:
                    # Si no se encuentra con el monto exacto, buscar con una tolerancia
                    # para manejar diferencias de redondeo
                    tolerance = 0.01  # 1 centavo de tolerancia
                    pos_payment = self.env['pos.payment'].search([
                        ('session_id', '=', pos_session_id),
                        ('amount', '>=', pos_amount_corrected - tolerance),
                        ('amount', '<=', pos_amount_corrected + tolerance),
                        ('payment_method_id', '=', self.id)
                    ], order='id desc', limit=1)
                
                return pos_payment
        except Exception as e:
            _logger.error('Error al buscar pago POS relacionado: %s', str(e))
        
        return None

    def _procesar_en_segundo_plano(
        self,
        data,
        bus_channel_name,
        id_config,
        transaction_id,
        base_url_endpoint,
        pos_session_id,
        account_payment_id=None,
        user_id=None,
    ):
        """
        Bucle processFinancialPurchaseQuery (mismo hilo que usa el TPV tras el POST inicial).

        Si account_payment_id está definido, al finalizar se enlaza payment.transaction al pago
        contable y se ejecuta action_post si ITD quedó en estado aprobado (mismo resultado
        operativo que un pos.payment en el front).
        """
        payment_method_id = self.id
        run_uid = user_id if user_id is not None else SUPERUSER_ID
        tid_norm = str(transaction_id).strip()

        with self.pool.cursor() as new_cr:
            env = api.Environment(new_cr, run_uid, {})
            try:
                query_data = {
                    'PosID': data['PosID'],
                    'SystemId': data['SystemId'],
                    'Branch': data['Branch'],
                    'ClientAppId': data['ClientAppId'],
                    'UserId': data['UserId'],
                    'TransactionDateTimeyyyyMMddHHmmssSSS': env['pos.payment.method'].get_formatted_timestamp(),
                    'TransactionId': transaction_id,
                }
                pm = env['pos.payment.method'].browse(payment_method_id)
                result = env['pos.payment.method'].fiserv_run_purchase_query_loop(
                    pm,
                    query_data,
                    base_url_endpoint,
                    transaction_id,
                    pos_session_id,
                    original_purchase_data=data,
                )
                try:
                    # --- No usar _update_stored_transaction_with_session: odoo_pos_oca la redefine
                    #     con 3 args y gana el MRO, rompiendo account_payment_id (TypeError). ---
                    pm._fiserv_persist_transaction_after_query(
                        tid_norm,
                        result,
                        pos_session_id,
                        account_payment_id=account_payment_id,
                    )
                except Exception as err_upd:
                    _logger.error('Error al actualizar transacción en segundo plano: %s', str(err_upd))

                result.update({
                    'id_config': id_config,
                    'origin_transaction_id': transaction_id,
                })
                # --- TPV: notificar bus; account.payment: nunca (proceso contable aislado) ---
                send_bus = not account_payment_id
                if send_bus and bus_channel_name:
                    try:
                        env['bus.bus'].sudo()._sendone(
                            bus_channel_name, 'FISERV_LATEST_RESPONSE', result
                        )
                    except Exception as bus_err:
                        _logger.error('Error al enviar mensaje bus: %s', str(bus_err))

                if account_payment_id:
                    pay = env['account.payment'].browse(account_payment_id)
                    # --- Mensaje para bus + soft_reload en el formulario (evita F5 manual) ---
                    bus_posted = False
                    bus_message = ''
                    if pay.exists():
                        tx = env['payment.transaction'].sudo().search(
                            [('fiserv_transaction_id', '=', tid_norm)],
                            limit=1,
                        )
                        if tx:
                            tx.write(
                                {
                                    'account_payment_id': account_payment_id,
                                    'transaction_origin': 'account_payment',
                                }
                            )
                        vals_pending = {'fiserv_async_terminal_pending': False}
                        # --- Vincular tx al pago estándar (account_payment / portal) si el campo existe ---
                        if tx and 'payment_transaction_id' in pay._fields:
                            vals_pending['payment_transaction_id'] = tx.id
                        pay.write(vals_pending)
                        state = env['payment.transaction']._get_transaction_state_with_pos_response(
                            str(result.get('ResponseCode', '999')).strip(),
                            result,
                        )
                        # --- Persistir ITD antes de contabilizar: si action_post falla, no se pierde el cobro ---
                        new_cr.commit()
                        pay = env['account.payment'].browse(account_payment_id)
                        if state == 'done':
                            try:
                                pay.action_post()
                                bus_posted = True
                                bus_message = _(
                                    'El cobro en el terminal finalizó y el pago quedó registrado.'
                                )
                            except Exception as post_err:
                                _logger.exception(
                                    'Fiserv: ITD aprobado pero action_post falló (pay=%s)',
                                    account_payment_id,
                                )
                                err_txt = getattr(post_err, 'name', None) or str(post_err)
                                pay.message_post(
                                    body=_(
                                        'Fiserv ITD: el cobro quedó aprobado en el terminal y la transacción '
                                        'quedó vinculada a este pago, pero al registrar en contabilidad falló:\n'
                                        '%(err)s\n\n'
                                        'Corrija la causa (p. ej. diarios, multimoneda, localización) y pulse '
                                        'Confirmar otra vez: no se volverá a enviar al pinpad.'
                                    )
                                    % {'err': err_txt}
                                )
                                bus_message = _(
                                    'El terminal aprobó el cobro, pero falló el registro contable. '
                                    'Revise el chatter de este pago.'
                                )
                        else:
                            if pay.payment_type == 'outbound':
                                body_txt = _(
                                    'Fiserv ITD (devolución): la anulación no quedó aprobada en el terminal '
                                    '(estado %(st)s). %(msg)s'
                                ) % {'st': state, 'msg': result.get('msg') or ''}
                            else:
                                body_txt = _(
                                    'Fiserv ITD: el cobro no quedó aprobado en el terminal '
                                    '(estado %(st)s). %(msg)s'
                                ) % {'st': state, 'msg': result.get('msg') or ''}
                            pay.message_post(body=body_txt)
                            bus_message = body_txt
                        env['account.payment']._fiserv_bus_notify_after_terminal(
                            run_uid,
                            account_payment_id,
                            bus_posted,
                            bus_message,
                        )
                new_cr.commit()
            except Exception:
                _logger.exception(
                    'Fiserv _procesar_en_segundo_plano falló (account_payment_id=%s, tx=%s)',
                    account_payment_id,
                    tid_norm,
                )
                new_cr.rollback()
                if account_payment_id and run_uid:
                    try:
                        with self.pool.cursor() as cr_bus:
                            env_bus = api.Environment(cr_bus, run_uid, {})
                            env_bus['account.payment']._fiserv_bus_notify_after_terminal(
                                run_uid,
                                account_payment_id,
                                False,
                                _(
                                    'Error al procesar la respuesta del terminal Fiserv. '
                                    'Revise el registro de pago y el chatter.'
                                ),
                            )
                            cr_bus.commit()
                    except Exception:
                        _logger.exception('Fiserv: notificación bus tras error en hilo')
            finally:
                if account_payment_id:
                    with self.pool.cursor() as cr2:
                        env2 = api.Environment(cr2, run_uid, {})
                        p2 = env2['account.payment'].browse(account_payment_id)
                        if p2.exists() and p2.fiserv_async_terminal_pending:
                            p2.write({'fiserv_async_terminal_pending': False})
                        cr2.commit()

    def _update_stored_transaction(self, transaction_id, final_result):
        """
        Actualiza la transacción almacenada con la información final del procesamiento
        O crea la transacción si no existe (cuando tenemos información completa)
        
        Args:
            transaction_id (str): ID de la transacción Fiserv
            final_result (dict): Resultado final del procesamiento
        """
        try:
            # Buscar la transacción por el ID ITD
            transaction = self.env['payment.transaction'].sudo().search([
                ('fiserv_transaction_id', '=', transaction_id)
            ], limit=1)
            
            if transaction:
                # Si la transacción ya existe, actualizarla
                transaction.update_fiserv_transaction(final_result)
                _logger.info('Transacción Fiserv actualizada exitosamente con información final')
            else:
                # Si la transacción no existe, crearla con la información completa
                # Esto sucede cuando la respuesta inicial fue exitosa y ahora tenemos todos los datos
                self._create_fiserv_transaction_with_complete_data(transaction_id, final_result)
                _logger.info('Transacción Fiserv creada exitosamente con información completa')
                
        except Exception as e:
            _logger.error('Error al actualizar/crear transacción Fiserv: %s', str(e))

    def _create_fiserv_transaction_with_complete_data(
        self,
        transaction_id,
        final_result,
        pos_session_id=None,
        account_payment_id=None,
    ):
        """
        Crea una transacción Fiserv con la información completa del POS
        
        Args:
            transaction_id (str): ID de la transacción Fiserv
            final_result (dict): Resultado final con información completa
            pos_session_id (int): ID de la sesión POS (opcional)
            account_payment_id (int|None): Pago contable (cobro backend); partner/compañía y payment_transaction_id.
        """
        try:
            _logger.info('Creando transacción Fiserv con información completa para ID: %s', transaction_id)
            
            pos_session = None
            pos_order = None
            pos_payment = None
            
            if pos_session_id:
                # Usar directamente el ID de la sesión si está disponible
                pos_session = self.env['pos.session'].browse(pos_session_id)
                if pos_session.exists():
                    _logger.info('Usando sesión POS proporcionada: %s', pos_session_id)
                    pos_order = self._find_related_pos_order_by_transaction(transaction_id, pos_session_id)
                    pos_payment = self._find_related_pos_payment_by_transaction(transaction_id, pos_session_id)
                else:
                    _logger.warning('Sesión POS %s no existe, buscando alternativas', pos_session_id)
                    pos_session = None
            
            if not pos_session:
                # Cobro contable (account.payment): no asociar a sesión/pedido POS aunque exista una caja abierta
                if account_payment_id:
                    _logger.info(
                        'Transacción Fiserv desde account.payment (sin vínculo POS): tx=%s',
                        transaction_id,
                    )
                    self.env['payment.transaction'].sudo().create_fiserv_transaction_with_complete_data(
                        itd_response=final_result,
                        pos_order=None,
                        pos_payment=None,
                        transaction_id=transaction_id,
                        account_payment_id=account_payment_id or False,
                    )
                    return
                # Buscar el pedido POS relacionado usando el transaction_id
                pos_session = self._find_session_by_transaction_id(transaction_id)

                if not pos_session:
                    _logger.warning('No se encontró sesión POS para la transacción: %s. Creando transacción sin relaciones.', transaction_id)
                    # Crear la transacción sin relaciones específicas
                    self.env['payment.transaction'].sudo().create_fiserv_transaction_with_complete_data(
                        itd_response=final_result,
                        pos_order=None,
                        pos_payment=None,
                        transaction_id=transaction_id,
                        account_payment_id=account_payment_id or False,
                    )
                    return
                
                # Buscar el pedido POS relacionado
                pos_order = self._find_related_pos_order_by_transaction(transaction_id, pos_session.id)
                pos_payment = self._find_related_pos_payment_by_transaction(transaction_id, pos_session.id)
            
            _logger.info('Relaciones encontradas - Sesión: %s, Pedido: %s, Pago: %s', 
                        pos_session.id, pos_order.id if pos_order else 'None', pos_payment.id if pos_payment else 'None')
            
            # Crear la transacción con información completa
            transaction = self.env['payment.transaction'].sudo().create_fiserv_transaction_with_complete_data(
                itd_response=final_result,
                pos_order=pos_order,
                pos_payment=pos_payment,
                transaction_id=transaction_id,
                account_payment_id=account_payment_id or False,
            )
            
            _logger.info('Transacción Fiserv creada exitosamente con ID: %s', transaction.id)
            
        except Exception as e:
            _logger.error('Error al crear transacción Fiserv con información completa: %s', str(e))
            # Intentar crear la transacción sin relaciones como último recurso
            try:
                self.env['payment.transaction'].sudo().create_fiserv_transaction_with_complete_data(
                    itd_response=final_result,
                    pos_order=None,
                    pos_payment=None,
                    transaction_id=transaction_id,
                    account_payment_id=account_payment_id or False,
                )
                _logger.info('Transacción Fiserv creada sin relaciones como fallback')
            except Exception as fallback_error:
                _logger.error('Error al crear transacción Fiserv como fallback: %s', str(fallback_error))

    def _find_session_by_transaction_id(self, transaction_id):
        """
        Busca la sesión POS relacionada con una transacción
        
        Args:
            transaction_id (str): ID de la transacción Fiserv
            
        Returns:
            pos.session: Sesión POS encontrada o None
        """
        _logger.info('Buscando sesión POS para transacción: %s', transaction_id)
        
        # Primero, intentar buscar en las transacciones existentes
        existing_transaction = self.env['payment.transaction'].sudo().search([
            ('fiserv_transaction_id', '=', transaction_id)
        ], limit=1)
        
        if existing_transaction:
            _logger.info('Transacción ya existe, usando sesión existente')
            if existing_transaction.pos_order_id and existing_transaction.pos_order_id.session_id:
                return existing_transaction.pos_order_id.session_id
            elif existing_transaction.pos_payment_id and existing_transaction.pos_payment_id.session_id:
                return existing_transaction.pos_payment_id.session_id
        
        # Buscar en las sesiones recientes que tengan pagos Fiserv
        recent_sessions = self.env['pos.session'].search([
            ('state', '=', 'opened')
        ], order='id desc', limit=20)  # Aumentar el límite para buscar más sesiones
        
        _logger.info('Sesiones abiertas encontradas: %s', len(recent_sessions))
        
        for session in recent_sessions:
            _logger.info('Verificando sesión: %s', session.id)
            
            # Buscar pagos Fiserv en esta sesión
            fiserv_payments = self.env['pos.payment'].search([
                ('session_id', '=', session.id),
                ('payment_method_id', '=', self.id)
            ])

            _logger.info('Pagos Fiserv en sesión %s: %s', session.id, len(fiserv_payments))

            if fiserv_payments:
                _logger.info('Sesión POS encontrada: %s', session.id)
                return session
        
        # Si no se encuentra con pagos Fiserv, buscar la sesión más reciente
        # que tenga cualquier tipo de pago (fallback)
        _logger.info('No se encontró sesión con pagos Fiserv, buscando sesión más reciente')
        
        recent_sessions_with_payments = self.env['pos.session'].search([
            ('state', '=', 'opened'),
            ('order_ids', '!=', False)  # Sesiones que tengan pedidos
        ], order='id desc', limit=5)
        
        for session in recent_sessions_with_payments:
            _logger.info('Verificando sesión con pedidos: %s', session.id)
            
            # Verificar si tiene pedidos recientes
            recent_orders = self.env['pos.order'].search([
                ('session_id', '=', session.id)
            ], order='id desc', limit=1)
            
            if recent_orders:
                _logger.info('Sesión POS encontrada (fallback): %s', session.id)
                return session
        
        _logger.error('No se encontró ninguna sesión POS válida para la transacción: %s', transaction_id)
        return None

    @api.model
    def processFinancialPurchaseQuery(self, data, base_url_endpoint):
        """
        Consulta el estado de una transacción financiera
        
        Args:
            data (dict): Datos de la consulta
            base_url_endpoint (str): URL base del endpoint
            
        Returns:
            dict: Respuesta de la consulta
        """
        endpoint = (base_url_endpoint or '').rstrip('/') + '/processFinancialPurchaseQuery'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)

        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        return response_json

    def cancelFinancialPurchase(self, data):
        """
        Cancela una compra financiera
        
        Args:
            data (dict): Datos de la cancelación
            
        Returns:
            dict: Respuesta de la cancelación
        """
        self.ensure_one()
        TIMEOUT = 30

        _logger.info('cancelFinancialPurchase by user #%d:\n%s', self.env.uid, pprint.pformat(data))

        base_url = (self.sudo().url_webservice or '').rstrip('/')
        endpoint = base_url + '/cancelFinancialPurchase'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=TIMEOUT)

        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        _logger.info('cancelFinancialPurchase Response:\n%s', pprint.pformat(response_json))
        return response_json

    def get_ticket_number(self, refunded_ids, amount_to_send):
        """
        Obtiene el número de ticket para una devolución
        
        Args:
            refunded_ids (list): IDs de las líneas reembolsadas
            amount_to_send (float): Monto a enviar
            
        Returns:
            dict: Información del ticket
        """
        self.ensure_one()
        pos_order_line_ids = self.env['pos.order.line'].search([('id', 'in', refunded_ids)])
        payments_ids = pos_order_line_ids.mapped('order_id').mapped('payment_ids').filtered(lambda l: l.payment_method_id == self)

        if not payments_ids:
            return False

        # Find the payment with the amount closest to amount_to_send
        closest_payment_id = min(payments_ids, key=lambda p: abs(p.amount - amount_to_send))
        response = {
            'TicketNumber': closest_payment_id.ticket,
            'Acquirer': closest_payment_id.card_type,
        }
        return response

    def processFinancialPurchaseVoidByTicket(self, data, pos_session_id, account_payment_id=None):
        """
        Anulación por ticket ITD; el bucle de consultas corre en el mismo hilo que la compra.

        Args:
            data (dict): Payload void por ticket.
            pos_session_id (int): Sesión POS (canal bus).
            account_payment_id (int|None): Pago contable «Enviar dinero» si aplica.

        Returns:
            dict: Respuesta inicial ITD.
        """
        self.ensure_one()
        _logger.info('Metodo processFinancialPurchaseVoidByTicket %s', pprint.pformat(data))

        base_url_endpoint, response_json = self._fiserv_http_post_void_by_ticket(data)

        # Almacenar la transacción en payment.transaction SOLO cuando recibimos respuesta del POS
        # PERO solo si la respuesta es exitosa y tenemos información completa
        if response_json['ResponseCode'] == '0':
            # Solo almacenar la transacción cuando tengamos información completa
            # La información completa llega después del procesamiento en segundo plano
            pass
        else:
            # Para respuestas de error, almacenar inmediatamente
            self._store_fiserv_transaction(data, response_json, pos_session_id or False)

        if response_json['ResponseCode'] == '0':
            transaction_id = response_json['TransactionId']
            bus_channel_name, id_config = self._fiserv_bus_channel_and_config(
                pos_session_id, account_payment_id=account_payment_id
            )
            store_sid = pos_session_id if pos_session_id else False
            threading.Thread(
                target=self._procesar_en_segundo_plano,
                args=(
                    data,
                    bus_channel_name,
                    id_config,
                    transaction_id,
                    base_url_endpoint,
                    store_sid,
                    account_payment_id,
                    self.env.uid if account_payment_id else None,
                ),
            ).start()

        return response_json

    def processFinancialReverse(self, data, base_url_endpoint):
        """
        Procesa una reversión financiera
        
        Args:
            data (dict): Datos de la reversión
            base_url_endpoint (str): URL base del endpoint
            
        Returns:
            dict: Respuesta de la reversión
        """
        self.ensure_one()

        _logger.info('processFinancialReverse by user #%d:\n%s', self.env.uid, pprint.pformat(data))

        endpoint = (base_url_endpoint or '').rstrip('/') + '/processFinancialReverse'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        _fiserv_normalize_itd_http_response(response_json)
        _logger.info('processFinancialReverse Response:\n%s', pprint.pformat(response_json))
        return response_json

    def _fiserv_persist_transaction_after_query(
        self,
        transaction_id,
        final_result,
        pos_session_id,
        account_payment_id=None,
    ):
        """
        Persiste el resultado final del bucle Query (crear o actualizar payment.transaction).

        Se separa de _update_stored_transaction_with_session porque odoo_pos_oca redefine ese
        método con firma (tx_id, result, pos_session_id) y en instalaciones OCA+Fiserv gana el
        MRO, ignorando account_payment_id y provocando TypeError al pasar el kwarg.

        Args:
            transaction_id (str): ID ITD (TransactionId).
            final_result (dict): Última respuesta ITD del pinpad.
            pos_session_id (int|bool): Sesión POS o False si el cobro es desde contabilidad.
            account_payment_id (int|None): Enlace a account.payment si aplica.
        """
        try:
            # --- ITD puede devolver TransactionId numérico; el campo Odoo es Char ---
            tid_key = str(transaction_id).strip()
            transaction = self.env['payment.transaction'].sudo().search(
                [('fiserv_transaction_id', '=', tid_key)],
                limit=1,
            )

            if transaction:
                transaction.update_fiserv_transaction(final_result)
                _logger.info(
                    'Transacción Fiserv actualizada tras Query (id ITD=%s)',
                    tid_key,
                )
            else:
                self._create_fiserv_transaction_with_complete_data(
                    tid_key,
                    final_result,
                    pos_session_id,
                    account_payment_id=account_payment_id,
                )
                _logger.info(
                    'Transacción Fiserv creada tras Query (id ITD=%s)',
                    tid_key,
                )

        except Exception as e:
            _logger.error('Error al persistir transacción Fiserv tras Query: %s', str(e))

    def _find_related_pos_order_by_transaction(self, transaction_id, pos_session_id):
        """
        Busca el pedido POS relacionado con una transacción.
        
        NOTA IMPORTANTE:
        Antes se usaba como fallback \"el último pedido de la sesión\", lo que
        provocaba que la transacción Fiserv quedara asociada a la orden anterior
        en vez de a la orden que se está creando ahora.
        
        Ahora, este método NO fuerza ninguna asociación por fallback y deja
        la transacción sin pos_order_id para que sea pos.order._associate_fiserv_transactions()
        quien realice la asociación definitiva una vez creada la orden POS.
        
        Args:
            transaction_id (str): ID de la transacción Fiserv
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.order: Recordset vacío cuando no se puede determinar con certeza
        """
        _logger.info(
            'Fiserv POS: _find_related_pos_order_by_transaction no aplicará fallback para transacción %s en sesión %s. '
            'La asociación se hará después desde pos.order._associate_fiserv_transactions.',
            transaction_id,
            pos_session_id,
        )
        return self.env['pos.order']

    def _find_related_pos_payment_by_transaction(self, transaction_id, pos_session_id):
        """
        Busca el pago POS relacionado con una transacción.
        
        Igual que con el pedido, antes se usaba como fallback \"el último pago
        Fiserv de la sesión\", lo que podía asociar la transacción al pago de una
        orden anterior. Esto generaba inconsistencias cuando se procesaban
        varias ventas seguidas.
        
        Ahora NO se aplica ese fallback y se deja la transacción sin
        pos_payment_id; la asociación se hará luego mediante:
        - pos.payment._associate_fiserv_transaction()
        - y, en promociones, la extensión correspondiente si aplica.
        
        Args:
            transaction_id (str): ID de la transacción Fiserv
            pos_session_id (int): ID de la sesión POS
            
        Returns:
            pos.payment: Recordset vacío cuando no se puede determinar con certeza
        """
        _logger.info(
            'Fiserv POS: _find_related_pos_payment_by_transaction no aplicará fallback para transacción %s en sesión %s. '
            'La asociación del pago se hará después desde pos.payment._associate_fiserv_transaction.',
            transaction_id,
            pos_session_id,
        )
        return self.env['pos.payment'] 