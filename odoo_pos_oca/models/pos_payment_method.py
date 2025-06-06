import threading
import pprint
import logging
import requests

from time import sleep
from odoo import fields, models, api, SUPERUSER_ID
from datetime import datetime

from odoo.addons.l10n_be_coda.models.account_journal import transaction_code

_logger = logging.getLogger("POS PAYMENT METHOD")


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super(PosPaymentMethod, self)._get_payment_terminal_selection() + [('oca', 'OCA')]

    def get_formatted_timestamp(self):
        now = datetime.now()
        return now.strftime('%Y%m%d%H%M%S') + f'{int(now.microsecond / 1000):03d}'

    url_webservice = fields.Char('URL servicio web')
    codigo_sistema = fields.Char('Código Sistema (SystemId)')
    codigo_terminal = fields.Char('Código Terminal (PosID)')
    client_app_id = fields.Char('Client APP ID', default='1')
    codigo_sucursal = fields.Integer('Código Sucursal')


    def enviar_pago(self, data, pos_session_id, has_refunded_line):
        self.ensure_one()
        if not has_refunded_line:
            return self.processFinancialPurchase(data, pos_session_id)

        return self.processFinancialPurchaseVoidByTicket(data, pos_session_id)

    def processFinancialPurchase(self, data, pos_session_id):
        self.ensure_one()
        _logger.info('Metodo processFinancialPurchase %s', pprint.pformat(data))

        base_url_endpoint = self.sudo().url_webservice
        endpoint = base_url_endpoint + '/processFinancialPurchase'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]

        _logger.info('processFinancialPurchase Response:\n%s', pprint.pformat(response_json))

        pos_session_sudo = self.env["pos.session"].sudo().browse(pos_session_id)
        bus_channel_name = pos_session_sudo._get_bus_channel_name()
        id_config = pos_session_sudo.config_id.id

        if response_json['ResponseCode'] == '0':
            # Iniciar hilo para procesamiento en segundo plano
            transaction_id = response_json['TransactionId']
            threading.Thread(target=self._procesar_en_segundo_plano, args=(data, bus_channel_name, id_config, transaction_id, base_url_endpoint)).start()

        return response_json

    def _procesar_en_segundo_plano(self, data, bus_channel_name, id_config, transaction_id, base_url_endpoint):
        # Nuevo cursor y entorno para evitar problemas de ORM compartido
        with self.pool.cursor() as new_cr:
            env = api.Environment(new_cr, SUPERUSER_ID, {})
            result = {}

            data = {
                "PosID": data['PosID'],
                "SystemId": data['SystemId'],
                "Branch": data['Branch'],
                "ClientAppId": data['ClientAppId'],
                "UserId": data['UserId'],
                "TransactionDateTimeyyyyMMddHHmmssSSS": self.get_formatted_timestamp(),
                "TransactionId": transaction_id,
            }

            while True:
                sleep(4)
                _logger.info('>>>Intento>>>')
                try:
                    result = env['pos.payment.method'].processFinancialPurchaseQuery(data, base_url_endpoint)
                    _logger.info('Result: %s', pprint.pformat(result))

                    response_code = result['ResponseCode']
                    rt = result['RemainingExpirationTime'] if 'RemainingExpirationTime' in result else False
                    if response_code not in ['10', '12']:
                        break

                    # if response_code == '12' and rt and rt == 0.0:
                    #     self.processFinancialReverse(data, base_url_endpoint)

                except Exception as e:
                    break
                _logger.info('>>>FIN Intento>>>')

            # Luego puedes enviar un mensaje al POS usando el bus
            result.update({
                'id_config': id_config,
                'origin_transaction_id': transaction_id,
            })
            env['bus.bus'].sudo()._sendone(bus_channel_name, 'OCA_LATEST_RESPONSE', result)

    @api.model
    def processFinancialPurchaseQuery(self, data, base_url_endpoint):
        endpoint = base_url_endpoint + '/processFinancialPurchaseQuery'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)

        response_json = req.json()

        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
            '0': 'Resultado OK',
            '10': 'Aguardando por operación en el pinpad.',
            '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
            '12': 'Pinpad consultó datos (se pasó la tarjeta).',
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]
        return response_json

    def cancelFinancialPurchase(self, data):
        self.ensure_one()
        TIMEOUT = 30

        _logger.info('cancelFinancialPurchase by user #%d:\n%s', self.env.uid, pprint.pformat(data))

        endpoint = self.sudo().url_webservice + '/cancelFinancialPurchase'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=TIMEOUT)

        response_json = req.json()

        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
            '0': 'Resultado OK',
            '10': 'Aguardando por operación en el pinpad.',
            '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
            '12': 'Pinpad consultó datos (se pasó la tarjeta).',
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
        response_json['msg'] = response_code_msg[response_json['ResponseCode']]
        _logger.info('cancelFinancialPurchase Response:\n%s', pprint.pformat(response_json))
        return response_json

    def get_ticket_number(self, refunded_ids, amount_to_send):
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

    def processFinancialPurchaseVoidByTicket(self, data, pos_session_id):
        self.ensure_one()
        _logger.info('Metodo processFinancialPurchaseVoidByTicket %s', pprint.pformat(data))

        base_url_endpoint = self.sudo().url_webservice
        endpoint = base_url_endpoint + '/processFinancialPurchaseVoidByTicket'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]

        _logger.info('processFinancialPurchaseVoidByTicket Response:\n%s', pprint.pformat(response_json))

        pos_session_sudo = self.env["pos.session"].sudo().browse(pos_session_id)
        bus_channel_name = pos_session_sudo._get_bus_channel_name()
        id_config = pos_session_sudo.config_id.id

        if response_json['ResponseCode'] == '0':
            # Iniciar hilo para procesamiento en segundo plano
            transaction_id = response_json['TransactionId']
            threading.Thread(target=self._procesar_en_segundo_plano, args=(data, bus_channel_name, id_config, transaction_id, base_url_endpoint)).start()

        return response_json

    def processFinancialReverse(self, data, base_url_endpoint):
        self.ensure_one()

        _logger.info('processFinancialReverse by user #%d:\n%s', self.env.uid, pprint.pformat(data))

        endpoint = base_url_endpoint + '/processFinancialReverse'
        headers = {
            'Content-Type': 'application/json',
        }
        req = requests.post(endpoint, json=data, headers=headers, timeout=30)
        response_json = req.json()
        response_json['ResponseCode'] = str(response_json['ResponseCode'])

        response_code_msg = {
            '0': 'Resultado OK',
            '10': 'Aguardando por operación en el pinpad.',
            '11': 'Tiempo de transacción excedido, envíe datos nuevamente.',
            '12': 'Pinpad consultó datos (se pasó la tarjeta).',
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

        response_json['msg'] = response_code_msg[response_json['ResponseCode']]
        _logger.info('processFinancialReverse Response:\n%s', pprint.pformat(response_json))
        return response_json
