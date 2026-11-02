# -*- coding: utf-8 -*-
"""Cada llamada a OCA queda registrada con lo que se mandó y lo que respondió.

Antes la transacción guardaba sólo los datos del cobro y la respuesta final. No golpea la
red: la función `post` se reemplaza.
"""
import json
from unittest.mock import patch

import requests

from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_oca_core.models import oca_utils
from odoo.addons.odoo_pos_oca_core.models.oca_envio import oca_post

URL = 'https://poslink.invalid/api'
COMPRA = {'PosID': '22224597', 'Amount': '39900', 'Currency': '858', 'InvoiceNumber': '1'}


class _Respuesta:
    def __init__(self, status, datos):
        self.status_code = status
        self.text = json.dumps(datos) if isinstance(datos, dict) else datos

    def json(self):
        return json.loads(self.text)


def _post(status, datos):
    return lambda endpoint, json=None, headers=None, timeout=None: _Respuesta(status, datos)


@tagged('post_install', '-at_install', 'oca_envios')
class TestLlamadasOca(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Envio = self.env['oca.envio']

    def _ultima(self):
        return self.Envio.search([], limit=1)

    def test_compra_queda_con_lo_mandado_y_la_respuesta(self):
        oca_post(self.env, _post(200, {'ResponseCode': 0, 'TransactionId': 777001, 'msg': 'OK'}),
                 URL + '/processFinancialPurchase', json=COMPRA, headers={}, timeout=30)
        reg = self._ultima()
        self.assertEqual(reg.operacion, 'processFinancialPurchase')
        self.assertEqual(reg.resultado, 'exito')
        self.assertEqual(reg.response_code, '0')
        self.assertEqual(reg.pos_id, '22224597')
        self.assertEqual(reg.oca_transaction_id, '777001')
        self.assertEqual(json.loads(reg.request), COMPRA)

    def test_consultas_iguales_suman_repeticiones(self):
        consulta = {'PosID': '22224597', 'TransactionId': 777002, 'TransactionDateTimeyyyyMMddHHmmssSSS': '1'}
        esperando = _post(200, {'ResponseCode': 10, 'msg': 'Aguardando por operación en el pinpad.'})
        for hora in ('1', '2', '3'):
            oca_post(self.env, esperando, URL + '/processFinancialPurchaseQuery',
                     json=dict(consulta, TransactionDateTimeyyyyMMddHHmmssSSS=hora))
        oca_post(self.env, _post(200, {'ResponseCode': 0, 'msg': 'Resultado OK'}),
                 URL + '/processFinancialPurchaseQuery', json=consulta)
        regs = self.Envio.search([('oca_transaction_id', '=', '777002')], order='id')
        self.assertEqual(regs.mapped('repeticiones'), [3, 1])
        self.assertEqual(regs.mapped('response_code'), ['10', '0'])

    def test_sin_respuesta_queda_registrado_y_se_propaga(self):
        def caida(*args, **kwargs):
            raise requests.exceptions.ConnectionError('conexión rechazada')
        try:
            oca_post(self.env, caida, URL + '/processFinancialPurchase', json=COMPRA)
        except requests.exceptions.ConnectionError:
            pass
        else:
            self.fail('no propagó el error')
        reg = self._ultima()
        self.assertEqual(reg.resultado, 'error')
        self.assertIn('conexión rechazada', reg.error)

    def test_error_http_desde_el_cobro_contable(self):
        with patch.object(oca_utils.requests, 'post', return_value=_Respuesta(500, 'Internal error')):
            _base, respuesta = oca_utils.oca_pos_http_post(
                URL, '/processFinancialPurchase', COMPRA, 'processFinancialPurchase', env=self.env)
        self.assertEqual(respuesta['ResponseCode'], '999')
        reg = self._ultima()
        self.assertEqual((reg.resultado, reg.status_http), ('rechazado', 500))
        self.assertEqual(reg.respuesta, 'Internal error')

    def test_la_transaccion_muestra_sus_llamadas(self):
        oca_post(self.env, _post(200, {'ResponseCode': 0, 'TransactionId': 777003}),
                 URL + '/processFinancialPurchase', json=COMPRA)
        oca_post(self.env, _post(200, {'ResponseCode': 0, 'TransactionId': 999999}),
                 URL + '/processFinancialPurchase', json=COMPRA)
        tx = self.env['payment.transaction'].sudo().create_oca_transaction_with_complete_data(
            {'ResponseCode': '0', 'msg': 'OK', 'TransactionId': 777003},
            transaction_id='777003', pos_data=dict(COMPRA))
        self.assertEqual(tx.oca_envio_ids.mapped('oca_transaction_id'), ['777003'])
