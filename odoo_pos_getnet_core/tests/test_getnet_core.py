# -*- coding: utf-8 -*-
"""
Tests del core Getnet/TransAct: cliente SOAP, mapeo de moneda, montos del
anexo del manual, lock de terminal y motor de polling (incluida la carrera
timeout -> cancelar -> aprobada).

Todo el transporte SOAP está mockeado: no se invoca ningún WS real.
"""

import itertools
import uuid
from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils
from odoo.addons.odoo_pos_getnet_core.models import (
    payment_transaction as pt_mod,
)


class FakeDriver:
    """Driver de polling con respuestas SOAP guionadas."""

    def __init__(self, script):
        # script: lista de (data, request_xml, response_xml) en orden de llamada
        self.script = list(script)
        self.calls = []

    def _getnet_soap_transaccion(self, method, params):
        self.calls.append((method, params))
        return self.script.pop(0)


def resp(data):
    """Atajo para una entrada de script."""
    return (data, '<req/>', '<resp/>')


# Nombres y valores tal como los declara el WSDL real de testing:
# Resp_EstadoAvance es una enumeración de STRINGS, el flag se llama
# Resp_TransaccionFinalizada y el código del autorizador CodRespAdq.
EN_PROCESO = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_ENPROCESO',
    'Resp_TransaccionFinalizada': 'false',
    'Resp_TokenSegundosReConsultar': '2',
}
APROBADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE',
    'Resp_TransaccionFinalizada': 'true',
    'Aprobada': 'true',
    'TransaccionId': '123456',
    'Ticket': '789',
    'Lote': '12',
    'NroAutorizacion': 'A99887',
    'TarjetaId': '2',
    'TarjetaTipo': 'CRE',
    'Cuotas': '1',
    'MsgRespuesta': 'APROBADA',
    'Voucher': ['LINEA 1', 'LINEA 2'],
}
DENEGADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_ERROR',
    'Resp_TransaccionFinalizada': 'true',
    'Aprobada': 'false',
    'CodRespAdq': '51',
    'MsgRespuesta': 'DENEGADA',
}
CANCELADA = {
    'Resp_CodigoRespuesta': '0',
    'Resp_EstadoAvance': 'ESTADOAVANCE_CANCELADA',
    'Resp_TransaccionFinalizada': 'true',
    'MsgRespuesta': 'CANCELADA',
}


def cierre_consulta_soap(procesadores, finalizado=True):
    """
    Respuesta realista de ConsultarCierre, con la estructura del WSDL.

    Incluye a propósito el subárbol Productos > Monedas > Planes >
    Nacionales > Venta, donde los nombres de totales (CantVenta/MontoVenta)
    se REPITEN: si algún día se vuelve a leer del dict aplanado, estos
    subtotales inflan los totales y el test lo detecta.
    """
    bloques = []
    for proc in procesadores:
        bloques.append("""
          <d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosCierre>
            <d:Aprobado>{aprobado}</d:Aprobado>
            <d:CodRespuesta>00</d:CodRespuesta>
            <d:Extendida>
              <d:CantAnulacion>{cant_anul}</d:CantAnulacion>
              <d:CantDevolucion>{cant_dev}</d:CantDevolucion>
              <d:CantVenta>{cant_venta}</d:CantVenta>
              <d:MontoAnulacion>{monto_anul}</d:MontoAnulacion>
              <d:MontoDevolucion>{monto_dev}</d:MontoDevolucion>
              <d:MontoVenta>{monto_venta}</d:MontoVenta>
              <d:Productos>
                <d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProducto>
                  <d:ProductoNombre>VISA</d:ProductoNombre>
                  <d:Monedas>
                    <d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProductoMoneda>
                      <d:MonedaISO>0858</d:MonedaISO>
                      <d:Planes>
                        <d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProductoMonedaPlan>
                          <d:Nacionales>
                            <d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProductoMonedaPlanDecretos>
                              <d:Venta>
                                <d:CantVenta>{cant_venta}</d:CantVenta>
                                <d:MontoVenta>{monto_venta}</d:MontoVenta>
                              </d:Venta>
                            </d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProductoMonedaPlanDecretos>
                          </d:Nacionales>
                        </d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProductoMonedaPlan>
                      </d:Planes>
                    </d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProductoMoneda>
                  </d:Monedas>
                </d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosProducto>
              </d:Productos>
            </d:Extendida>
            <d:Lote>{lote}</d:Lote>
            <d:NroAutorizacion>Z1</d:NroAutorizacion>
            <d:ProcesadorId>{procesador}</d:ProcesadorId>
          </d:ITarjetasCierre_400.RespuestaConsultarCierre.IDatosCierre>
        """.format(**proc))
    return """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <ConsultarCierreResponse xmlns="http://tempuri.org/">
      <ConsultarCierreResult xmlns:d="{dc}" xmlns:a="{arr}">
        <d:DatosCierre>{bloques}</d:DatosCierre>
        <d:Estado>CERRADO</d:Estado>
        <d:Resp_CierreFinalizado>{fin}</d:Resp_CierreFinalizado>
        <d:Resp_CodigoRespuesta>0</d:Resp_CodigoRespuesta>
        <d:Resp_EstadoAvance>ESTADOAVANCE_FINALIZADA_CORRECTAMENTE</d:Resp_EstadoAvance>
        <d:TokenNro>TOK-CIERRE</d:TokenNro>
        <d:Voucher>
          <a:string>CIERRE DE LOTE</a:string>
          <a:string>TOTAL VENTAS</a:string>
        </d:Voucher>
      </ConsultarCierreResult>
    </ConsultarCierreResponse>
  </s:Body>
</s:Envelope>""".format(
        dc=getnet_utils.GETNET_DATACONTRACT_NS,
        arr=getnet_utils.GETNET_ARRAYS_NS,
        bloques=''.join(bloques),
        fin='true' if finalizado else 'false')


def cierre_resp(procesadores, finalizado=True):
    """Entrada de script de cierre a partir de una respuesta SOAP real."""
    xml = cierre_consulta_soap(procesadores, finalizado)
    return (getnet_utils.getnet_parse_soap_response(xml.encode('utf-8')),
            '<req/>', xml)


CIERRE_EXPIRADO_XML = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <ConsultarCierreResponse xmlns="http://tempuri.org/">
      <ConsultarCierreResult xmlns:d="%s">
        <d:DatosCierre/>
        <d:Estado>EXPIRADA(POS NO BUSCO TRANSACCION)</d:Estado>
        <d:Resp_CierreFinalizado>true</d:Resp_CierreFinalizado>
        <d:Resp_CodigoRespuesta>0</d:Resp_CodigoRespuesta>
        <d:Resp_EstadoAvance>ESTADOAVANCE_FINALIZADA_ERROR</d:Resp_EstadoAvance>
        <d:TokenNro>TOK-EXP</d:TokenNro>
      </ConsultarCierreResult>
    </ConsultarCierreResponse>
  </s:Body>
</s:Envelope>""" % getnet_utils.GETNET_DATACONTRACT_NS


PROC_DEFAULT = {
    'aprobado': 'true', 'lote': '12', 'procesador': '0',
    'cant_venta': '3', 'monto_venta': '45000',
    'cant_anul': '1', 'monto_anul': '10000',
    'cant_dev': '0', 'monto_dev': '0',
}

CANCEL_OK = {'Resp_CodigoRespuesta': '0'}
CANCEL_FAIL = {
    'Resp_CodigoRespuesta': '1',
    'Resp_MensajeError': 'No se puede cancelar una transacción confirmada',
}


@tagged('post_install', '-at_install')
class TestGetnetCore(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Getnet Test',
            'code': 'getnet',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE',
            # Valor inventado: el hash real (integración o producción) va
            # SOLO en el provider de la BD, nunca en código ni fixtures.
            'getnet_emp_hash': 'FAKEHASH00000000FAKEHASH00000000',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Caja 1',
            'term_cod': 'T00001',
            'payment_provider_id': cls.provider.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Getnet'})
        # Blindaje: si la DB trae transacciones getnet en vuelo de corridas
        # previas, sacarlas del alcance del cron de recuperación para que
        # los tests de "no debe consultar" no den falsos negativos.
        cls.env['payment.transaction'].search([
            ('provider_id.code', '=', 'getnet'),
            ('state', 'in', ('draft', 'pending')),
            ('getnet_token', '!=', False),
        ]).write({'getnet_token': False})
        cls.payment_method = cls.env['payment.method'].search([], limit=1)
        if not cls.payment_method:
            cls.payment_method = cls.env['payment.method'].create({
                'name': 'Getnet Test Method',
                'code': 'getnet_test',
            })
        cls.uyu = cls.env.ref('base.UYU')
        cls.usd = cls.env.ref('base.USD')
        cls.eur = cls.env.ref('base.EUR')

    def _create_tx(self, **vals):
        base = {
            'provider_id': self.provider.id,
            'payment_method_id': self.payment_method.id,
            'reference': 'GETNET-TEST-%s' % uuid.uuid4().hex[:12],
            'amount': 100.0,
            'currency_id': self.uyu.id,
            'partner_id': self.partner.id,
            'getnet_token': 'TOKEN-1',
            'getnet_terminal_id': self.terminal.id,
        }
        base.update(vals)
        return self.env['payment.transaction'].create(base)

    def _run_loop(self, tx, driver, monotonic_seq, **kwargs):
        """Ejecuta el loop con tiempo controlado (sin sleeps reales)."""
        with patch.object(pt_mod.time, 'sleep', lambda s: None), \
                patch.object(pt_mod.time, 'monotonic',
                             side_effect=list(monotonic_seq)):
            return tx.getnet_run_query_loop(driver, tx.getnet_token, **kwargs)

    # ------------------------------------------------------------------
    # Cliente SOAP
    # ------------------------------------------------------------------
    def test_soap_envelope_build(self):
        """El envelope serializa anidados, booleanos y omite None."""
        envelope = getnet_utils.getnet_build_soap_envelope(
            'PostearTransaccion', {
                'Transaccion': {
                    'EmpCod': 'NEWAGE',
                    'Operacion': 'VTA',
                    'FacturaConsumidorFinal': True,
                    # DecretoLeyId sin setear (None) = comportamiento
                    # recomendado del manual: el POS lo pide al cajero.
                    'Extendida': {'Cuotas': 1, 'DecretoLeyId': None},
                },
            })
        text = envelope.decode('utf-8')
        self.assertIn('PostearTransaccion', text)
        self.assertIn('<dc:EmpCod>NEWAGE</dc:EmpCod>', text)
        self.assertIn('<dc:FacturaConsumidorFinal>true</dc:FacturaConsumidorFinal>', text)
        self.assertIn('<dc:Cuotas>1</dc:Cuotas>', text)
        self.assertNotIn('DecretoLeyId', text)

    def test_soap_envelope_namespaces_del_contrato(self):
        """
        El wrapper del método va en tempuri y los campos del tipo complejo
        en el namespace de DataContract (elementFormDefault=qualified de
        los XSD). Si se emiten todos en tempuri, WCF los ignora y el
        concentrador recibe EmpCod/EmpHASH nulos.
        """
        envelope = getnet_utils.getnet_build_soap_envelope(
            'PostearTransaccion',
            {'Transaccion': {'EmpCod': 'NEWAGE', 'TermCod': 'T00001'}})
        root = etree.fromstring(envelope)
        metodo = root.find('.//{%s}PostearTransaccion' % getnet_utils.GETNET_SOAP_NS)
        self.assertIsNotNone(metodo)
        wrapper = metodo.find('{%s}Transaccion' % getnet_utils.GETNET_SOAP_NS)
        self.assertIsNotNone(wrapper, 'El parámetro Transaccion va en tempuri')
        self.assertIsNotNone(
            wrapper.find('{%s}EmpCod' % getnet_utils.GETNET_DATACONTRACT_NS),
            'Los campos del tipo complejo van en el namespace DataContract')

    def test_soap_envelope_orden_del_contrato(self):
        """
        DataContractSerializer recorre el xs:sequence: un elemento fuera de
        orden se saltea en silencio y el campo llega nulo. El builder emite
        siempre en el orden del contrato, sin importar el orden del dict.
        """
        envelope = getnet_utils.getnet_build_soap_envelope(
            'PostearTransaccion', {
                'Transaccion': {
                    'TicketOriginal': 99,
                    'Monto': 15000,
                    'EmpCod': 'NEWAGE',
                    'Configuracion': {'ModoEmulacion': True},
                    'Operacion': 'DEV',
                },
            })
        root = etree.fromstring(envelope)
        wrapper = root.find('.//{%s}Transaccion' % getnet_utils.GETNET_SOAP_NS)
        nombres = [etree.QName(hijo).localname for hijo in wrapper]
        self.assertEqual(
            nombres,
            ['Configuracion', 'EmpCod', 'Monto', 'Operacion', 'TicketOriginal'])

    def test_soap_envelope_campo_ajeno_al_contrato(self):
        """Un campo inexistente falla fuerte en vez de viajar nulo."""
        with self.assertRaises(ValueError):
            getnet_utils.getnet_build_soap_envelope(
                'PostearTransaccion',
                {'Transaccion': {'EmpCod': 'NEWAGE', 'MontoTotal': 100}})

    def test_estado_avance_enum_string(self):
        """Resp_EstadoAvance es una enumeración de strings en el WSDL."""
        self.assertEqual(
            getnet_utils.getnet_estado_avance(
                {'Resp_EstadoAvance': 'ESTADOAVANCE_CANCELADA'}),
            getnet_utils.ESTADOAVANCE_CANCELADA)
        self.assertIn(
            getnet_utils.getnet_estado_avance(
                {'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE'}),
            getnet_utils.ESTADOS_FINALES)
        self.assertEqual(
            getnet_utils.getnet_estado_avance({}),
            getnet_utils.ESTADOAVANCE_SINDEFINIR)

    def test_parse_voucher_array_of_string(self):
        """
        El Voucher es un ArrayOfstring: los renglones cuelgan de <string>
        en el namespace de Arrays. Aplanar por nombre de hoja los dejaba
        bajo la clave 'string' y el voucher quedaba vacío.
        """
        xml = ("""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
          <s:Body>
            <ConsultarTransaccionResponse xmlns="http://tempuri.org/">
              <ConsultarTransaccionResult xmlns:d="%s" xmlns:a="%s">
                <d:Resp_CodigoRespuesta>0</d:Resp_CodigoRespuesta>
                <d:Aprobada>true</d:Aprobada>
                <d:Ticket>789</d:Ticket>
                <d:CodRespAdq>00</d:CodRespAdq>
                <d:Voucher>
                  <a:string>GETNET S.A.</a:string>
                  <a:string>TOTAL 150,00</a:string>
                </d:Voucher>
              </ConsultarTransaccionResult>
            </ConsultarTransaccionResponse>
          </s:Body>
        </s:Envelope>""" % (getnet_utils.GETNET_DATACONTRACT_NS,
                            getnet_utils.GETNET_ARRAYS_NS)).encode('utf-8')
        data = getnet_utils.getnet_parse_soap_response(xml)
        self.assertEqual(data['Voucher'], ['GETNET S.A.', 'TOTAL 150,00'])
        self.assertEqual(data['CodRespAdq'], '00')
        self.assertNotIn('string', data)

    def test_entero_contrato(self):
        """TicketOriginal es xs:int aunque el Ticket llegue como double."""
        self.assertEqual(
            getnet_utils.getnet_entero_contrato('789.0', 'TicketOriginal'), 789)
        self.assertEqual(
            getnet_utils.getnet_entero_contrato('789', 'TicketOriginal'), 789)
        self.assertIsNone(
            getnet_utils.getnet_entero_contrato('', 'TicketOriginal'))
        with self.assertRaises(ValueError):
            getnet_utils.getnet_entero_contrato('A-123', 'TicketOriginal')

    def test_soap_parse_response(self):
        """Parseo aplanado de una respuesta WCF, con Voucher como lista."""
        xml = b"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
          <s:Body>
            <PostearTransaccionResponse xmlns="http://tempuri.org/">
              <PostearTransaccionResult>
                <Resp_CodigoRespuesta>0</Resp_CodigoRespuesta>
                <TokenNro>ABC123</TokenNro>
                <TokenSegundosConsultar>5</TokenSegundosConsultar>
                <Voucher>LINEA 1</Voucher>
                <Voucher>LINEA 2</Voucher>
              </PostearTransaccionResult>
            </PostearTransaccionResponse>
          </s:Body>
        </s:Envelope>"""
        data = getnet_utils.getnet_parse_soap_response(xml)
        self.assertEqual(data['Resp_CodigoRespuesta'], '0')
        self.assertEqual(data['TokenNro'], 'ABC123')
        self.assertEqual(data['Voucher'], ['LINEA 1', 'LINEA 2'])
        self.assertEqual(getnet_utils.getnet_segundos_reconsulta(data, 99), 5)

    def test_soap_parse_fault(self):
        """Un SOAP Fault se normaliza como error de transporte sintético."""
        xml = b"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
          <s:Body>
            <s:Fault>
              <faultcode>s:Client</faultcode>
              <faultstring>Hash invalido</faultstring>
            </s:Fault>
          </s:Body>
        </s:Envelope>"""
        data = getnet_utils.getnet_parse_soap_response(xml)
        self.assertEqual(
            getnet_utils.getnet_rc(data), getnet_utils.GETNET_RC_TRANSPORTE)
        self.assertIn('Hash invalido', data['Resp_MensajeError'])

    def test_soap_parse_basura(self):
        """Respuesta no-XML tampoco lanza: RC de transporte."""
        data = getnet_utils.getnet_parse_soap_response(b'<html>gateway error')
        self.assertEqual(
            getnet_utils.getnet_rc(data), getnet_utils.GETNET_RC_TRANSPORTE)

    # ------------------------------------------------------------------
    # Moneda y montos
    # ------------------------------------------------------------------
    def test_moneda_iso(self):
        """UYU->0858, USD->0840, otra moneda rechaza con error claro."""
        self.assertEqual(getnet_utils.getnet_moneda_iso('UYU'), '0858')
        self.assertEqual(getnet_utils.getnet_moneda_iso('USD'), '0840')
        with self.assertRaises(ValueError):
            getnet_utils.getnet_moneda_iso('EUR')
        self.assertEqual(self.provider._getnet_moneda_iso(self.uyu), '0858')
        self.assertEqual(self.provider._getnet_moneda_iso(self.usd), '0840')
        with self.assertRaises(UserError):
            self.provider._getnet_moneda_iso(self.eur)

    def test_montos_factura_anexo_manual(self):
        """
        Regresión permanente: anexo del manual general. Factura con líneas
        22% / 10% / exento (neto 100 c/u) => FacturaMonto 33200,
        FacturaMontoGravado 20000 (neto gravado sin importar tasa),
        FacturaMontoIVA 3200. Alimenta la devolución de IVA ley 19210.
        """
        montos = getnet_utils.getnet_montos_factura([
            (100.0, 22.0),   # tasa básica
            (100.0, 10.0),   # tasa mínima
            (100.0, 0.0),    # exento
        ])
        self.assertEqual(montos['FacturaMonto'], 33200)
        self.assertEqual(montos['FacturaMontoGravado'], 20000)
        self.assertEqual(montos['FacturaMontoIVA'], 3200)

    def test_base_vals_y_credenciales(self):
        vals = self.provider._getnet_base_transaccion_vals(self.terminal)
        self.assertEqual(vals['EmpCod'], 'NEWAGE')
        self.assertEqual(vals['TermCod'], 'T00001')
        self.assertTrue(vals['EmpHASH'])
        sin_hash = self.provider.copy({'getnet_emp_hash': False})
        with self.assertRaises(UserError):
            sin_hash._getnet_base_transaccion_vals(self.terminal)

    # ------------------------------------------------------------------
    # Lock de terminal (invariante cross-flujo)
    # ------------------------------------------------------------------
    def test_terminal_lock_cross_flujo(self):
        """
        Posteo concurrente backend + POS a la misma terminal: el segundo
        flujo debe rechazarse mientras el primero tenga el lock.
        """
        self.terminal.getnet_claim('account_payment', ref='TOKEN-BACK')
        with self.assertRaises(UserError):
            self.terminal.getnet_claim('pos', ref='TOKEN-POS')
        self.terminal.getnet_release()
        # Liberada, el POS puede tomarla
        self.assertTrue(self.terminal.getnet_claim('pos', ref='TOKEN-POS'))
        self.terminal.getnet_release()

    def test_terminal_lock_takeover_huerfano(self):
        """Un lock vencido (worker muerto) puede ser tomado por otro flujo."""
        self.terminal.getnet_claim('pos', ref='TOKEN-VIEJO')
        # Envejecemos el lock más allá del TTL
        self.env.cr.execute(
            "UPDATE getnet_pos_terminal SET lock_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(seconds=9999), self.terminal.id),
        )
        self.terminal.invalidate_recordset()
        self.assertTrue(
            self.terminal.getnet_claim('account_payment', ref='TOKEN-NUEVO'))
        self.assertEqual(self.terminal.lock_origin, 'account_payment')
        self.terminal.getnet_release()

    def test_terminal_touch_mantiene_lock(self):
        """El touch del polling evita que un flujo vivo venza por TTL."""
        self.terminal.getnet_claim('pos', ref='TOKEN-VIVO')
        self.env.cr.execute(
            "UPDATE getnet_pos_terminal SET lock_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(seconds=9999), self.terminal.id),
        )
        self.terminal.getnet_touch()
        self.terminal.invalidate_recordset()
        with self.assertRaises(UserError):
            self.terminal.getnet_claim('account_payment')
        self.terminal.getnet_release()

    # ------------------------------------------------------------------
    # Motor de polling
    # ------------------------------------------------------------------
    def test_poll_aprobada(self):
        """Camino feliz: en proceso -> aprobada; persiste datos y done."""
        tx = self._create_tx()
        driver = FakeDriver([resp(EN_PROCESO), resp(APROBADA)])
        result = self._run_loop(tx, driver, [0, 10, 20])
        self.assertFalse(result['timeout'])
        self.assertFalse(result['cancel_attempted'])
        tx.getnet_persist_query_result(result)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.getnet_ticket, '789')
        self.assertEqual(tx.getnet_lote, '12')
        self.assertEqual(tx.getnet_nro_autorizacion, 'A99887')
        self.assertEqual(tx.getnet_voucher, 'LINEA 1\nLINEA 2')
        self.assertEqual(tx.getnet_cuotas, 1)
        # Solo consultas, sin cancelaciones
        self.assertEqual(
            [c[0] for c in driver.calls],
            ['ConsultarTransaccion', 'ConsultarTransaccion'])

    def test_poll_denegada(self):
        tx = self._create_tx()
        driver = FakeDriver([resp(DENEGADA)])
        result = self._run_loop(tx, driver, [0, 5])
        tx.getnet_persist_query_result(result)
        self.assertEqual(tx.state, 'error')
        self.assertIn('51', tx.state_message)

    def test_poll_transporte_no_corta(self):
        """Errores de transporte no cortan el loop (obligación de consultar)."""
        tx = self._create_tx()
        transporte = {
            'Resp_CodigoRespuesta': str(getnet_utils.GETNET_RC_TRANSPORTE),
            'Resp_MensajeError': 'HTTP 502',
        }
        driver = FakeDriver([resp(transporte), resp(APROBADA)])
        result = self._run_loop(tx, driver, [0, 5, 10])
        tx.getnet_persist_query_result(result)
        self.assertEqual(tx.state, 'done')

    def test_poll_carrera_timeout_cancel_falla_luego_aprobada(self):
        """
        LA carrera crítica: vence el timeout general, se intenta cancelar,
        el cancel FALLA porque el POS ya aprobó, y la consulta siguiente
        trae la aprobación. La transacción debe quedar 'done' con todos los
        datos — nunca fallida por el timeout local (sería un cobro real en
        el pinpad sin pago en Odoo).
        """
        tx = self._create_tx()
        driver = FakeDriver([
            resp(EN_PROCESO),      # consulta 1: en proceso (elapsed 10)
            resp(EN_PROCESO),      # consulta 2: en proceso (elapsed 200 > 180)
            resp(CANCEL_FAIL),     # cancelación rechazada (ya aprobada)
            resp(APROBADA),        # consulta 3: llega la aprobación real
        ])
        result = self._run_loop(tx, driver, [0, 10, 200, 210])
        self.assertTrue(result['cancel_attempted'])
        self.assertFalse(result['cancel_ok'])
        self.assertFalse(result['timeout'])
        tx.getnet_persist_query_result(result)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.getnet_ticket, '789')
        self.assertEqual(
            [c[0] for c in driver.calls],
            ['ConsultarTransaccion', 'ConsultarTransaccion',
             'CancelarTransaccion', 'ConsultarTransaccion'])

    def test_poll_timeout_cancel_ok(self):
        """Timeout general con cancelación exitosa: estado 'cancel'."""
        tx = self._create_tx()
        driver = FakeDriver([
            resp(EN_PROCESO),      # consulta 1 (elapsed 10)
            resp(EN_PROCESO),      # consulta 2 (elapsed 200 > 180)
            resp(CANCEL_OK),       # cancelación aceptada
            resp(CANCELADA),       # consulta 3 confirma CANCELADA
        ])
        result = self._run_loop(tx, driver, [0, 10, 200, 210])
        self.assertTrue(result['cancel_attempted'])
        self.assertTrue(result['cancel_ok'])
        tx.getnet_persist_query_result(result)
        self.assertEqual(tx.state, 'cancel')

    def test_poll_hard_max_deja_pendiente(self):
        """
        Sin respuesta final tras hard_max (cancel fallido incluido): la
        transacción queda 'pending' para conciliación manual, NUNCA 'error'.
        """
        tx = self._create_tx()
        driver = FakeDriver([
            resp(EN_PROCESO),      # consulta 1 (elapsed 10)
            resp(EN_PROCESO),      # consulta 2 (elapsed 200): cancel
            resp(CANCEL_FAIL),
            resp(EN_PROCESO),      # consulta 3 (elapsed 950 > hard_max)
        ])
        result = self._run_loop(tx, driver, [0, 10, 200, 950])
        self.assertTrue(result['timeout'])
        tx.getnet_persist_query_result(result)
        self.assertEqual(tx.state, 'pending')
        self.assertIn('TOKEN-1', tx.state_message)

    # ------------------------------------------------------------------
    # Finalizado != exitoso (auditoría del mismo error que tenía el cierre)
    # ------------------------------------------------------------------
    def test_finalizada_error_marca_fallida_sin_lote(self):
        """
        ESTADOAVANCE_FINALIZADA_ERROR es final pero NO exitoso: la
        transacción queda en error, sin lote registrado.
        """
        tx = self._create_tx()
        denegada = dict(DENEGADA, Lote='7')
        driver = FakeDriver([resp(denegada)])
        tx.getnet_persist_query_result(self._run_loop(tx, driver, [0, 5]))
        self.assertEqual(tx.state, 'error')
        self.assertFalse(self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id)]))

    def test_lote_cero_no_crea_registro_de_cierre(self):
        """
        El concentrador manda Lote='0' para "sin lote" (visto en testing):
        como texto es truthy y creaba un lote fantasma.
        """
        tx = self._create_tx()
        aprobada_sin_lote = dict(APROBADA, Lote='0')
        driver = FakeDriver([resp(aprobada_sin_lote)])
        tx.getnet_persist_query_result(self._run_loop(tx, driver, [0, 5]))
        self.assertEqual(tx.state, 'done')
        self.assertFalse(tx.getnet_lote)
        self.assertFalse(self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id)]))

    def test_respuesta_contradictoria_queda_pendiente(self):
        """
        Aprobada=true con estado final de error: no se resuelve en ningún
        sentido (ni cobro registrado ni fracaso declarado).
        """
        tx = self._create_tx()
        contradictoria = dict(APROBADA,
                              Resp_EstadoAvance='ESTADOAVANCE_FINALIZADA_ERROR')
        driver = FakeDriver([resp(contradictoria)])
        tx.getnet_persist_query_result(self._run_loop(tx, driver, [0, 5]))
        self.assertEqual(tx.state, 'pending')
        self.assertFalse(self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id)]))

    def test_contradictoria_sale_del_cron_y_entra_al_filtro(self):
        """
        La contradicción llega en una respuesta FINAL: re-consultarla
        devuelve siempre lo mismo. Debe quedar marcada para conciliación,
        el cron tiene que saltearla y tiene que aparecer en el filtro.
        """
        tx = self._create_tx(getnet_token='TOK-CONTRA')
        contradictoria = dict(APROBADA,
                              Resp_EstadoAvance='ESTADOAVANCE_FINALIZADA_ERROR')
        driver = FakeDriver([resp(contradictoria)])
        tx.getnet_persist_query_result(self._run_loop(tx, driver, [0, 5]))
        self.assertEqual(tx.state, 'pending')
        self.assertTrue(tx.getnet_requiere_conciliacion)
        self.assertIn('contradictoria', tx.getnet_motivo_conciliacion)

        # El cron no la toca: sin llamadas SOAP y sin cambio de estado
        self.terminal.getnet_release()
        tx.write({'write_date': fields.Datetime.now() - timedelta(hours=1)})
        llamadas = []

        def fake_soap(prov, method, params):
            llamadas.append(method)
            return resp(APROBADA)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertFalse(llamadas, 'el cron no debe re-consultarla')
        self.assertEqual(tx.state, 'pending')

        # Y es visible por el filtro/acción de conciliación
        pendientes = self.env['payment.transaction'].search([
            ('provider_code', '=', 'getnet'),
            ('getnet_requiere_conciliacion', '=', True)])
        self.assertIn(tx, pendientes)

        # Conciliada a mano vuelve al circuito normal
        tx.getnet_action_conciliada()
        self.assertFalse(tx.getnet_requiere_conciliacion)
        self.assertEqual(tx.getnet_recovery_intentos, 0)

    def test_no_autocrea_account_payment(self):
        """
        El post-procesamiento nativo de account_payment crea (y postea) un
        account.payment por cada transacción done sin payment_id. Para
        Getnet eso duplicaría el cobro: el pago contable ya existe y lo
        confirma el usuario, o el cobro es un pos.payment.
        """
        tx = self._create_tx()
        driver = FakeDriver([resp(APROBADA)])
        tx.getnet_persist_query_result(self._run_loop(tx, driver, [0, 5]))
        self.assertEqual(tx.state, 'done')
        antes = self.env['account.payment'].search_count([])
        creado = tx._create_payment()
        self.assertFalse(creado, 'no debe crear un pago propio')
        self.assertEqual(self.env['account.payment'].search_count([]), antes)
        self.assertFalse(tx.payment_id)

    def test_conciliada_exige_grupo_contabilidad(self):
        """
        La escritura va en sudo (el core solo da ACL de sistema), así que
        el permiso real lo pone la guarda del método: ocultar el botón no
        alcanza porque al método se llega también por RPC.
        """
        tx = self._create_tx(getnet_token='TOK-PERM')
        tx.getnet_marcar_conciliacion('prueba de permisos')
        ajeno = self.env['res.users'].create({
            'name': 'Sin contabilidad',
            'login': 'getnet_sin_conta_%s' % uuid.uuid4().hex[:8],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            tx.with_user(ajeno).getnet_action_conciliada()
        self.assertTrue(tx.getnet_requiere_conciliacion)

        contador = self.env['res.users'].create({
            'name': 'Contador',
            'login': 'getnet_conta_%s' % uuid.uuid4().hex[:8],
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id])],
        })
        tx.with_user(contador).getnet_action_conciliada()
        tx.invalidate_recordset()
        self.assertFalse(tx.getnet_requiere_conciliacion)

    def test_cron_corta_tras_max_intentos(self):
        """
        Sin respuesta final tras N pasadas: el cron deja de reintentar
        para siempre y la manda a conciliación manual.
        """
        tx = self._create_tx(getnet_token='TOK-SIN-FIN')
        self.terminal.getnet_release()

        def fake_soap(prov, method, params):
            # Nunca finaliza: el loop agota su hard-max en cada pasada
            return resp(EN_PROCESO)

        for pasada in range(pt_mod.GETNET_RECOVERY_MAX_INTENTOS):
            tx.write({'write_date': fields.Datetime.now() - timedelta(hours=1)})
            self.assertFalse(
                tx.getnet_requiere_conciliacion,
                'no debe cortar antes del tope (pasada %s)' % pasada)
            with patch.object(type(self.provider), '_getnet_soap_transaccion',
                              fake_soap), \
                    patch.object(pt_mod.time, 'sleep', lambda s: None), \
                    patch.object(pt_mod.time, 'monotonic',
                                 side_effect=itertools.count(0, 400)):
                self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertEqual(tx.getnet_recovery_intentos,
                         pt_mod.GETNET_RECOVERY_MAX_INTENTOS)
        self.assertTrue(tx.getnet_requiere_conciliacion)
        self.assertIn('intentos', tx.getnet_motivo_conciliacion)
        self.terminal.invalidate_recordset()
        self.assertFalse(self.terminal.lock_origin)

    def test_cron_resuelta_limpia_la_marca(self):
        """Si el cron la resuelve, la marca de conciliación se limpia."""
        tx = self._create_tx(getnet_token='TOK-LIMPIA')
        tx.getnet_marcar_conciliacion('marca previa de prueba')
        tx.getnet_action_conciliada()
        self.terminal.getnet_release()
        tx.write({'write_date': fields.Datetime.now() - timedelta(hours=1)})

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          lambda prov, m, p: resp(APROBADA)), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertEqual(tx.state, 'done')
        self.assertFalse(tx.getnet_requiere_conciliacion)

    def test_cron_recuperacion_finalizada_error(self):
        """El cron resuelve a error, no deja la transacción en vuelo."""
        tx = self._create_tx(getnet_token='TOK-CRON-ERR')
        self.terminal.getnet_release()
        tx.write({'write_date': fields.Datetime.now() - timedelta(hours=1)})

        def fake_soap(prov, method, params):
            return resp(DENEGADA)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertEqual(tx.state, 'error')
        self.assertFalse(self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id)]))
        self.terminal.invalidate_recordset()
        self.assertFalse(self.terminal.lock_origin)

    # ------------------------------------------------------------------
    # Cierre de lote (Fase 4)
    # ------------------------------------------------------------------
    def test_cierre_bloqueado_con_tx_en_vuelo(self):
        """Obs. 6: transacción en vuelo => cierre bloqueado con mensaje."""
        self._create_tx(getnet_token='TOK-VUELO')
        with self.assertRaises(UserError):
            self.terminal.getnet_cerrar_lote(force=False)
        # Y la terminal no quedó tomada por el intento fallido
        self.assertTrue(self.terminal.getnet_claim('pos'))
        self.terminal.getnet_release()

    def test_cierre_feliz_persiste_totales(self):
        """Lote Abierto -> Cerrado con totales; lock liberado."""
        tx = self._create_tx()
        driver = FakeDriver([resp(APROBADA)])
        result = self._run_loop(tx, driver, [0, 5])
        tx.getnet_persist_query_result(result)
        lote = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id),
            ('state', '=', 'abierto')])
        self.assertEqual(len(lote), 1)
        self.assertEqual(lote.lote, '12')

        script = [
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-CIERRE'}),
            cierre_resp([PROC_DEFAULT]),
        ]
        params_enviados = []

        def fake_cierre(prov, method, params):
            params_enviados.append((method, params))
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          fake_cierre), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.terminal.getnet_cerrar_lote(force=False)
        # El Cierre viaja envuelto en su parámetro, no aplanado en el método
        self.assertEqual(params_enviados[0][0], 'PostearCierre')
        self.assertIn('Cierre', params_enviados[0][1])
        self.assertEqual(
            params_enviados[0][1]['Cierre']['TermCod'], self.terminal.term_cod)
        self.assertEqual(lote.state, 'cerrado')
        self.assertTrue(lote.aprobado)
        self.assertEqual(lote.cant_venta, 3)
        self.assertAlmostEqual(lote.monto_venta, 450.0, places=2)
        self.assertAlmostEqual(lote.monto_anulacion, 100.0, places=2)
        self.terminal.invalidate_recordset()
        self.assertFalse(self.terminal.lock_origin)

    def test_cierre_totales_no_suman_subtotales_por_plan(self):
        """
        Los totales salen de DatosCierre[*].Extendida.

        Regresión del supuesto que traía el aplanado: los mismos nombres
        (CantVenta/MontoVenta) existen bajo Productos>Monedas>Planes y
        sumarlos duplicaba el cierre.
        """
        script = [
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-SUB'}),
            cierre_resp([PROC_DEFAULT]),
        ]

        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          lambda prov, m, p: script.pop(0)), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.terminal.getnet_cerrar_lote(force=False)
        cerrado = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id),
            ('state', '=', 'cerrado')], limit=1)
        # 3 ventas, no 6 (el subtotal del plan repite los mismos nombres)
        self.assertEqual(cerrado.cant_venta, 3)
        self.assertAlmostEqual(cerrado.monto_venta, 450.0, places=2)

    def test_cierre_multiples_procesadores_agrega_totales(self):
        """DatosCierre es un array: los totales se suman por procesador."""
        proc_b = dict(PROC_DEFAULT, procesador='1', lote='13',
                      cant_venta='2', monto_venta='30000',
                      cant_anul='0', monto_anul='0')
        script = [
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-MULTI'}),
            cierre_resp([PROC_DEFAULT, proc_b]),
        ]

        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          lambda prov, m, p: script.pop(0)), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.terminal.getnet_cerrar_lote(force=False)
        cerrado = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id),
            ('state', '=', 'cerrado')], limit=1)
        self.assertEqual(cerrado.cant_venta, 5)
        self.assertAlmostEqual(cerrado.monto_venta, 750.0, places=2)

    def test_cierre_expirado_no_cierra_lotes(self):
        """
        Caso real del concentrador de testing: el cierre "finaliza" con
        Resp_CierreFinalizado=true pero ESTADOAVANCE_FINALIZADA_ERROR,
        Estado='EXPIRADA(POS NO BUSCO TRANSACCION)' y DatosCierre vacío.
        Cerrar los lotes ahí sería perderlos sin cierre real en la terminal.
        """
        tx = self._create_tx()
        driver = FakeDriver([resp(APROBADA)])
        tx.getnet_persist_query_result(self._run_loop(tx, driver, [0, 5]))
        lote = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id),
            ('state', '=', 'abierto')], limit=1)
        self.assertTrue(lote)

        script = [
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-EXP'}),
            (getnet_utils.getnet_parse_soap_response(
                CIERRE_EXPIRADO_XML.encode('utf-8')),
             '<req/>', CIERRE_EXPIRADO_XML),
        ]
        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          lambda prov, m, p: script.pop(0)), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            with self.assertRaises(UserError):
                self.terminal.getnet_cerrar_lote(force=False)
        lote.invalidate_recordset()
        self.assertEqual(lote.state, 'abierto')
        # y la terminal quedó libre pese al error
        self.terminal.invalidate_recordset()
        self.assertFalse(self.terminal.lock_origin)

    def test_cierre_no_aprobado_si_algun_procesador_falla(self):
        """Un procesador no aprobado deja el cierre como no aprobado."""
        proc_malo = dict(PROC_DEFAULT, procesador='1', aprobado='false')
        script = [
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-NOK'}),
            cierre_resp([PROC_DEFAULT, proc_malo]),
        ]

        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          lambda prov, m, p: script.pop(0)), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.terminal.getnet_cerrar_lote(force=False)
        cerrado = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id),
            ('state', '=', 'cerrado')], limit=1)
        self.assertFalse(cerrado.aprobado)

    def test_cierre_forzado_procede_con_tx_en_vuelo(self):
        """Forzar (acción separada de admin) procede y deja rastro en log."""
        self._create_tx(getnet_token='TOK-VUELO-2')
        vacio = dict(PROC_DEFAULT, cant_venta='0', monto_venta='0',
                     cant_anul='0', monto_anul='0')
        script = [
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-C2'}),
            cierre_resp([vacio]),
        ]

        def fake_cierre(prov, method, params):
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          fake_cierre), \
                patch.object(pt_mod.time, 'sleep', lambda s: None), \
                self.assertLogs(
                    'odoo.addons.odoo_pos_getnet_core.models.'
                    'getnet_lote_cierre', level='WARNING') as logs:
            self.terminal.action_getnet_forzar_cierre_lote()
        self.assertTrue(any('FORZADO' in m for m in logs.output))

    def test_cierre_no_hay_pendientes_consulta_ultimo(self):
        """Fallback del manual: recuperar totales del último cierre."""
        calls = []
        ultimo = dict(PROC_DEFAULT, cant_venta='2', monto_venta='20000',
                      cant_anul='0', monto_anul='0')
        script = [
            resp({'Resp_CodigoRespuesta': '1',
                  'Resp_MensajeError': 'NO HAY CIERRES PENDIENTES'}),
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-ULT'}),
            cierre_resp([ultimo]),
        ]
        params_enviados = []

        def fake_cierre(prov, method, params):
            calls.append(method)
            params_enviados.append(params)
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_cierre',
                          fake_cierre), \
                patch.object(pt_mod.time, 'sleep', lambda s: None):
            self.terminal.getnet_cerrar_lote(force=False)
        self.assertEqual(calls[:2],
                         ['PostearCierre', 'PostearConsultaUltimoCierre'])
        # Cada método envuelve el Cierre con el nombre de parámetro propio
        self.assertIn('Cierre', params_enviados[0])
        self.assertIn('ConsultaUltimoCierre', params_enviados[1])
        cerrado = self.env['getnet.lote.cierre'].search([
            ('terminal_id', '=', self.terminal.id),
            ('state', '=', 'cerrado')], limit=1)
        self.assertEqual(cerrado.cant_venta, 2)

    # ------------------------------------------------------------------
    # Posteo con código 9
    # ------------------------------------------------------------------
    def test_postear_rc9_cancela_y_reintenta(self):
        """
        RC 9 (factura pendiente en la terminal): se cancela el token
        pendiente informado y se repostea una única vez.
        """
        script = [
            resp({'Resp_CodigoRespuesta': '9', 'TokenNro': 'PENDIENTE-1'}),
            resp(CANCEL_OK),
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'NUEVO-1',
                  'TokenSegundosConsultar': '5'}),
        ]
        calls = []

        def fake_soap(prov, method, params):
            calls.append((method, params))
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            data, _req, _resp = self.provider.getnet_postear_transaccion(
                {'EmpCod': 'NEWAGE'})
        self.assertEqual(data['TokenNro'], 'NUEVO-1')
        self.assertEqual(
            [c[0] for c in calls],
            ['PostearTransaccion', 'CancelarTransaccion',
             'PostearTransaccion'])
        self.assertEqual(calls[1][1], {'TokenNro': 'PENDIENTE-1'})

    def test_postear_rc9_cancel_falla_no_pisa(self):
        """Si el token pendiente no se puede cancelar, no se repostea."""
        script = [
            resp({'Resp_CodigoRespuesta': '9', 'TokenNro': 'PENDIENTE-1'}),
            resp(CANCEL_FAIL),
        ]

        def fake_soap(prov, method, params):
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            data, _req, _resp = self.provider.getnet_postear_transaccion(
                {'EmpCod': 'NEWAGE'})
        self.assertEqual(getnet_utils.getnet_rc(data), 9)

    def test_postear_rc9_token_propio_aprobado_no_se_cancela(self):
        """
        Takeover con token pendiente PROPIO ya aprobado en el pinpad: el
        handler de RC 9 debe consultarlo (no cancelarlo): la huérfana queda
        'done' con ticket/lote/autorización y el nuevo posteo procede.
        """
        huerfana = self._create_tx(getnet_token='ORF-1')
        script = [
            resp({'Resp_CodigoRespuesta': '9', 'TokenNro': 'ORF-1'}),
            resp(APROBADA),
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'NUEVO-1',
                  'TokenSegundosConsultar': '5'}),
        ]
        calls = []

        def fake_soap(prov, method, params):
            calls.append((method, params))
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            data, _req, _resp = self.provider.getnet_postear_transaccion(
                {'EmpCod': 'NEWAGE'})
        self.assertEqual(data['TokenNro'], 'NUEVO-1')
        self.assertEqual(
            [c[0] for c in calls],
            ['PostearTransaccion', 'ConsultarTransaccion',
             'PostearTransaccion'])
        self.assertEqual(huerfana.state, 'done')
        self.assertEqual(huerfana.getnet_ticket, '789')
        self.assertEqual(huerfana.getnet_lote, '12')
        self.assertEqual(huerfana.getnet_nro_autorizacion, 'A99887')

    def test_postear_rc9_token_propio_pendiente_se_cancela(self):
        """
        Token propio genuinamente sin finalizar: consulta -> sigue en
        proceso -> se cancela -> se persiste CANCELADA -> se repostea.
        """
        huerfana = self._create_tx(getnet_token='ORF-2')
        script = [
            resp({'Resp_CodigoRespuesta': '9', 'TokenNro': 'ORF-2'}),
            resp(EN_PROCESO),
            resp(CANCEL_OK),
            resp(CANCELADA),
            resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'NUEVO-2',
                  'TokenSegundosConsultar': '5'}),
        ]
        calls = []

        def fake_soap(prov, method, params):
            calls.append((method, params))
            return script.pop(0)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            data, _req, _resp = self.provider.getnet_postear_transaccion(
                {'EmpCod': 'NEWAGE'})
        self.assertEqual(data['TokenNro'], 'NUEVO-2')
        self.assertEqual(
            [c[0] for c in calls],
            ['PostearTransaccion', 'ConsultarTransaccion',
             'CancelarTransaccion', 'ConsultarTransaccion',
             'PostearTransaccion'])
        self.assertEqual(huerfana.state, 'cancel')

    # ------------------------------------------------------------------
    # Liberación del lock en el camino de error
    # ------------------------------------------------------------------
    def test_postear_con_lock_libera_en_excepcion(self):
        """
        Claim OK -> posteo explota -> lock liberado -> claim inmediato OK.

        Nota: try/except plano a propósito — el assertRaises de Odoo
        envuelve el bloque en un savepoint que revierte los efectos al
        capturar, y acá lo que se verifica son justamente los efectos
        persistidos tras la excepción.
        """
        def boom(prov, method, params):
            raise OSError('conexión caída')

        capturada = False
        try:
            with patch.object(type(self.provider), '_getnet_soap_transaccion',
                              boom):
                self.provider.getnet_postear_transaccion_con_lock(
                    self.terminal, {'EmpCod': 'NEWAGE'},
                    'account_payment', ref='TOKEN-X')
        except OSError:
            capturada = True
        self.assertTrue(capturada)
        # Sin esperar TTL: la terminal quedó libre
        self.assertTrue(self.terminal.getnet_claim('pos', ref='TOKEN-POS'))
        self.terminal.getnet_release()

    def test_postear_con_lock_libera_en_rc_error(self):
        """Posteo con RC != 0 (el polling no arranca): lock liberado."""
        def fake_soap(prov, method, params):
            return resp({'Resp_CodigoRespuesta': '2',
                         'Resp_MensajeError': 'Error de integración'})

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            data, _req, _resp = self.provider.getnet_postear_transaccion_con_lock(
                self.terminal, {'EmpCod': 'NEWAGE'},
                'account_payment', ref='TOKEN-X')
        self.assertEqual(getnet_utils.getnet_rc(data), 2)
        self.assertTrue(self.terminal.getnet_claim('pos', ref='TOKEN-POS'))
        self.terminal.getnet_release()

    def test_postear_con_lock_mantiene_lock_en_ok(self):
        """Posteo OK: el lock queda tomado para el worker de polling."""
        def fake_soap(prov, method, params):
            return resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-OK',
                         'TokenSegundosConsultar': '5'})

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            data, _req, _resp = self.provider.getnet_postear_transaccion_con_lock(
                self.terminal, {'EmpCod': 'NEWAGE'}, 'pos', ref='TOK-OK')
        self.assertEqual(data['TokenNro'], 'TOK-OK')
        with self.assertRaises(UserError):
            self.terminal.getnet_claim('account_payment')
        self.terminal.getnet_release()

    def test_postear_con_lock_falla_arranque_worker(self):
        """
        Posteo OK pero el lanzamiento del hilo de polling explota: el lock
        se libera ahí mismo (no espera el rescate por heartbeat) y la
        transacción queda 'pending' con su token para que el cron la
        resuelva.
        """
        tx = self._create_tx(getnet_token=False, getnet_terminal_id=False)

        def fake_soap(prov, method, params):
            return resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-W',
                         'TokenSegundosConsultar': '5'})

        def worker_boom(data):
            raise RuntimeError('no se pudo lanzar el hilo')

        # try/except plano: el assertRaises de Odoo revierte los efectos
        # persistidos dentro del bloque (savepoint), y son lo que se testea.
        capturada = False
        try:
            with patch.object(type(self.provider), '_getnet_soap_transaccion',
                              fake_soap):
                self.provider.getnet_postear_transaccion_con_lock(
                    self.terminal, {'EmpCod': 'NEWAGE'}, 'account_payment',
                    ref='TOK-W', tx=tx, start_worker=worker_boom)
        except RuntimeError:
            capturada = True
        self.assertTrue(capturada)
        # Token y terminal persistidos para el cron, estado pending
        self.assertEqual(tx.getnet_token, 'TOK-W')
        self.assertEqual(tx.getnet_terminal_id, self.terminal)
        self.assertEqual(tx.state, 'pending')
        # Lock liberado de inmediato
        self.assertTrue(self.terminal.getnet_claim('pos'))
        self.terminal.getnet_release()

    def test_postear_con_lock_worker_ok_mantiene_lock(self):
        """Worker arranca bien: el lock sigue tomado para su finally."""
        tx = self._create_tx(getnet_token=False, getnet_terminal_id=False)
        arrancado = []

        def fake_soap(prov, method, params):
            return resp({'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-W2',
                         'TokenSegundosConsultar': '5'})

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap):
            self.provider.getnet_postear_transaccion_con_lock(
                self.terminal, {'EmpCod': 'NEWAGE'}, 'pos',
                ref='TOK-W2', tx=tx, start_worker=arrancado.append)
        self.assertEqual(len(arrancado), 1)
        self.assertEqual(tx.getnet_token, 'TOK-W2')
        with self.assertRaises(UserError):
            self.terminal.getnet_claim('account_payment')
        self.terminal.getnet_release()

    # ------------------------------------------------------------------
    # Cron de recuperación
    # ------------------------------------------------------------------
    def test_cron_recupera_transaccion_sin_hilo(self):
        """
        Transacción en vuelo con worker muerto (lock propio con heartbeat
        vencido, TTL aún vigente): el cron libera, re-toma como 'recovery',
        la resuelve a 'done' y deja la terminal libre.
        """
        tx = self._create_tx(getnet_token='TOKEN-1')
        self.terminal.getnet_claim('pos', ref='TOKEN-1')
        # Heartbeat vencido (>120s) pero TTL del claim vigente (<600s)
        self.env.cr.execute(
            "UPDATE getnet_pos_terminal SET lock_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(seconds=300), self.terminal.id),
        )
        self.terminal.invalidate_recordset()

        def fake_soap(prov, method, params):
            return resp(APROBADA)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None), \
                patch.object(pt_mod.time, 'monotonic', side_effect=[0, 5]):
            self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.getnet_ticket, '789')
        self.terminal.invalidate_recordset()
        self.assertFalse(self.terminal.lock_origin)

    def test_cron_saltea_hilo_vivo(self):
        """
        Transacción cuyo hilo sigue vivo (touch reciente del lock con su
        token): el cron no debe tocarla ni invocar al WS.
        """
        tx = self._create_tx(getnet_token='TOKEN-1')
        self.terminal.getnet_claim('pos', ref='TOKEN-1')
        calls = []

        def fake_soap(prov, method, params):
            calls.append(method)
            return resp(APROBADA)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None), \
                patch.object(pt_mod.time, 'monotonic', side_effect=[0, 5]):
            self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertEqual(calls, [])
        self.assertEqual(tx.state, 'draft')
        self.terminal.invalidate_recordset()
        self.assertEqual(self.terminal.lock_origin, 'pos')
        self.terminal.getnet_release()

    def test_cron_saltea_terminal_ocupada_por_otro(self):
        """
        Terminal tomada por OTRA operación viva (lock_ref distinto): el
        cron saltea la transacción hasta la próxima pasada.
        """
        tx = self._create_tx(getnet_token='TOKEN-1')
        self.terminal.getnet_claim('account_payment', ref='OTRO-TOKEN')
        calls = []

        def fake_soap(prov, method, params):
            calls.append(method)
            return resp(APROBADA)

        with patch.object(type(self.provider), '_getnet_soap_transaccion',
                          fake_soap), \
                patch.object(pt_mod.time, 'sleep', lambda s: None), \
                patch.object(pt_mod.time, 'monotonic', side_effect=[0, 5]):
            self.env['payment.transaction']._getnet_cron_recover_inflight()
        self.assertEqual(calls, [])
        self.assertEqual(tx.state, 'draft')
        self.terminal.getnet_release()
