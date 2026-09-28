# -*- coding: utf-8 -*-
"""
Promociones por tarjeta, punta a punta por la puerta de la pantalla de cobro.

Se entra por `pos_backend.app` (preparar, sondear, cobrar, avisos, opciones)
con un CAJERO —no un administrador— y el SOAP guionado por método. La tarjeta
de las respuestas es la de la captura real del 26/09 (VISA / ITAU / débito /
BIN 421301); lo que la lectura previa devuelve está CONSTRUIDO a partir del
manual, porque sin WSDL no hay captura (ver getnet_supuestos_lectura.py).
"""

import uuid
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoo_pos_getnet_core.models import (
    payment_transaction as pt_mod,
)
from odoo.addons.odoo_pos_getnet_core.tests.common import _RelojDeLaboratorio
from odoo.addons.odoo_pos_getnet_promociones.models import (
    getnet_supuestos_lectura as supuestos,
)

POSTEO_OK = {'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-VTA',
             'Resp_TokenSegundosReConsultar': '1'}
LECTURA_OK = {'Resp_CodigoRespuesta': '0', 'TokenNro': 'TOK-LECT'}
LECTURA_ESPERANDO = {'Resp_CodigoRespuesta': '0', 'Resp_TransaccionFinalizada': 'false'}
VISA_ITAU = {'TarjetaId': '2', 'EmisorId': '12', 'TarjetaTipo': 'DEB',
             'TarjetaIIN': '421301'}
MASTER_BROU = {'TarjetaId': '1', 'EmisorId': '1', 'TarjetaTipo': 'CRE',
               'TarjetaIIN': '545454'}


def _leida(tarjeta):
    return dict({'Resp_CodigoRespuesta': '0', 'Resp_TransaccionFinalizada': 'true',
                 'TarjetaNro': '4213010000001234'}, **tarjeta)


def _aprobada(tarjeta, ticket='7001'):
    return dict({
        'Resp_CodigoRespuesta': '0',
        'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE',
        'Resp_TransaccionFinalizada': 'true', 'Aprobada': 'true',
        'TransaccionId': '88', 'Ticket': ticket, 'Lote': '4',
        'NroAutorizacion': 'B7', 'MsgRespuesta': 'APROBADA'}, **tarjeta)


DENEGADA = {'Resp_CodigoRespuesta': '0',
            'Resp_EstadoAvance': 'ESTADOAVANCE_FINALIZADA_ERROR',
            'Resp_TransaccionFinalizada': 'true', 'Aprobada': 'false',
            'CodRespAdq': '51', 'Ticket': '0', 'MsgRespuesta': 'SIN FONDOS'}


class _Deshacer(Exception):
    pass


@tagged('post_install', '-at_install')
class TestPromocionesGetnet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['payment.provider'].create({
            'name': 'Getnet Promos', 'code': 'getnet', 'state': 'test',
            'getnet_url_webservice': 'https://testing.example.invalid',
            'getnet_emp_cod': 'NEWAGE',
            'getnet_emp_hash': 'FAKEHASH00000000FAKEHASH00000000',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Pinpad Promos', 'term_cod': 'T00021',
            'payment_provider_id': cls.provider.id,
        })
        cls.local = cls.env['pos_backend.local'].create({'name': 'Local Promos'})
        cls.box = cls.env['pos_backend.box'].create(
            {'name': 'Caja Promos', 'local_id': cls.local.id})
        cls.company = cls.box.company_id
        journal = cls.env['account.journal'].create({
            'name': 'Tarjetas Promos', 'type': 'bank', 'code': 'TPRO',
            'company_id': cls.company.id,
        })
        caja = cls.env['account.journal'].create({
            'name': 'Caja Promos', 'type': 'cash', 'code': 'CPRO',
            'company_id': cls.company.id,
        })
        cls.metodo = cls.env['pos_backend.box.payment.method'].create({
            'box_id': cls.box.id, 'name': 'Getnet Promos',
            'payment_type': 'integrado', 'journal_id': journal.id,
            'available_for_collect': True, 'terminal_provider': 'getnet',
            'getnet_terminal_id': cls.terminal.id,
        })
        cls.efectivo = cls.env['pos_backend.box.payment.method'].create({
            'box_id': cls.box.id, 'name': 'Efectivo Promos',
            'payment_type': 'efectivo', 'journal_id': caja.id,
            'available_for_collect': True,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Promos'})
        cls.iva22 = cls.env['account.tax'].create({
            'name': 'IVA 22 promos', 'amount': 22, 'price_include_override': 'tax_included',
            'company_id': cls.company.id})
        cls.iva10 = cls.env['account.tax'].create({
            'name': 'IVA 10 promos', 'amount': 10, 'price_include_override': 'tax_included',
            'company_id': cls.company.id})
        cls.producto = cls.env['product.product'].create({'name': 'Producto Promos'})
        cls.producto_b = cls.env['product.product'].create({'name': 'Producto Promos B'})
        cls.producto_reintegro = cls.env['product.product'].create({
            'name': 'Reintegro banco', 'type': 'service'})
        Cuenta = cls.env['account.account']
        cls.cuenta_descuentos = Cuenta.create({
            'name': 'Descuentos concedidos promos', 'code': 'PRDESC1',
            'account_type': 'expense', 'company_ids': [(6, 0, cls.company.ids)]})
        cls.cuenta_reintegro = Cuenta.create({
            'name': 'Reintegros a cobrar promos', 'code': 'PRREIN1',
            'account_type': 'asset_current', 'company_ids': [(6, 0, cls.company.ids)]})
        # Aislamiento fiscal: sin un diario de ventas propio la factura cae en
        # el real y la localización emite el CFE de verdad dentro del test.
        cls.env['account.journal'].sudo().create({
            'name': 'Ventas Aisladas Promos', 'type': 'sale', 'code': 'VAIPR',
            'sequence': 1, 'company_id': cls.company.id,
            'l10n_latam_use_documents': False,
        })
        Promo = cls.env['getnet.promocion']
        Promo.search([('company_id', '=', cls.company.id)]).write({'active': False})
        cls.promo_itau = Promo.create({
            'name': 'ITAU débito 10', 'sequence': 1, 'emisor_id': '12',
            'tarjeta_tipo': 'DEB', 'porcentaje': 10, 'company_id': cls.company.id,
            'financia': 'campera', 'cuenta_id': cls.cuenta_descuentos.id})
        cls.promo_oca = Promo.create({
            'name': 'OCA 20', 'sequence': 2, 'emisor_id': '14',
            'porcentaje': 20, 'company_id': cls.company.id,
            'financia': 'banco', 'cuenta_id': cls.cuenta_reintegro.id})
        # El CAJERO, no un administrador: el flujo entero tiene que andar con
        # los permisos de quien cobra.
        cls.cajero = cls.env['res.users'].create({
            'name': 'Cajero Promos', 'login': 'cajero_promos_getnet',
            'email': 'cajero_promos_getnet@example.com',
            'group_ids': [(6, 0, [cls.env.ref('pos_backend.group_pos_cashier').id])],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'Manager Promos', 'login': 'manager_promos_getnet',
            'email': 'manager_promos_getnet@example.com',
            'group_ids': [(6, 0, [cls.env.ref('pos_backend.group_pos_manager').id])],
        })
        cls.app = cls.env['pos_backend.app'].with_user(cls.manager)
        cls.env['payment.transaction'].sudo().search([
            ('getnet_transaction_origin', '=', 'pos_backend'),
            ('state', '=', 'done'),
            ('getnet_requiere_conciliacion', '=', False),
        ]).write({'getnet_requiere_conciliacion': True})

    def setUp(self):
        super().setUp()
        impl = self.env['pos_backend.terminal.getnet']
        self.patch(type(impl), '_getnet_en_cursor_propio',
                   lambda modelo, trabajo: trabajo(self.env))
        self.patch(type(self.env['pos_backend.order']), '_check_receptor_identified',
                   lambda order: None)
        self.llamadas = []

    # ------------------------------------------------------------------
    def _pedido(self, lineas=((1000.0, None),)):
        sesion = self.env['pos_backend.session'].sudo().search(
            [('box_id', '=', self.box.id), ('state', '=', 'open')], limit=1)
        if not sesion:
            sesion = self.env['pos_backend.session'].sudo().create({
                'box_id': self.box.id, 'name': 'SES-PROMO-%s' % uuid.uuid4().hex[:6]})
        order = self.env['pos_backend.order'].with_user(self.manager).create({
            'partner_id': self.partner.id, 'local_id': self.local.id})
        for precio, impuesto in lineas:
            self.env['pos_backend.order.line'].with_user(self.manager).create({
                'order_id': order.id, 'product_id': self.producto.id,
                'quantity': 1.0, 'price_unit': precio,
                'tax_ids': [(6, 0, impuesto.ids if impuesto else [])]})
        order.action_send_to_collect()
        order.sudo()._workflow_write({
            'state': 'tomado', 'session_id': sesion.id, 'box_id': self.box.id})
        return order.with_user(self.manager)

    def _soap(self, guion):
        """guion: {metodo: [respuestas]}. Deja en self.llamadas lo posteado."""
        def fake(prov, metodo, params):
            self.llamadas.append((metodo, params))
            cola = guion.get(metodo)
            if not cola:
                raise AssertionError('llamada no guionada: %s' % metodo)
            return (dict(cola.pop(0)), '<req/>',
                    '<r><TarjetaNro>4213010000001234</TarjetaNro><TarjetaIIN>421301</TarjetaIIN></r>')
        return patch.object(type(self.provider), '_getnet_soap_transaccion', fake)

    def _reloj(self):
        return patch.object(pt_mod, 'time', _RelojDeLaboratorio([0, 1, 2]))

    def _posteos(self, metodo='PostearTransaccion'):
        return [p for m, p in self.llamadas if m == metodo]

    def _leer(self, order, tarjeta, app=None, monto=None):
        """Modo B: preparar, un sondeo esperando y otro con la tarjeta."""
        app = app or self.app
        guion = {supuestos.METODO_POSTEAR: [LECTURA_OK],
                 supuestos.METODO_CONSULTAR: [LECTURA_ESPERANDO, _leida(tarjeta)]}
        with self._soap(guion):
            r = app.prepare_terminal_payment(order.id, self.metodo.id,
                                             monto or order.amount_pending)
            self.assertEqual(r['state'], 'waiting', r.get('message'))
            r = app.poll_terminal_payment_preparation(order.id, self.metodo.id, r['token'])
            self.assertEqual(r['state'], 'waiting')
            return app.poll_terminal_payment_preparation(order.id, self.metodo.id, r['token'])

    def _cobrar(self, order, tarjeta, monto, app=None, ticket='7001'):
        app = app or self.app
        guion = {'PostearTransaccion': [POSTEO_OK],
                 'ConsultarTransaccion': [_aprobada(tarjeta, ticket)]}
        with self._soap(guion), self._reloj():
            app.add_payment_line(order.id, self.metodo.id, monto)
        return order.payment_line_ids.sorted('id')[-1]

    def _avisos(self, order, app=None):
        return (app or self.app).get_payment_screen_data(order.id)['order']['terminal_notices']

    def _eventos(self, order):
        return order.sudo().getnet_promocion_evento_ids.mapped('evento')

    # ==================================================================
    # Catálogo
    # ==================================================================
    def test_catalogo_sello_emisor_tipo_y_bin(self):
        Promo = self.env['getnet.promocion']
        self.assertEqual(Promo._buscar({'emisor_id': '12', 'tarjeta_tipo': 'DEB'}, self.company),
                         self.promo_itau)
        self.assertFalse(Promo._buscar({'emisor_id': '12', 'tarjeta_tipo': 'CRE'}, self.company))
        self.assertEqual(Promo._buscar({'emisor_id': 14}, self.company), self.promo_oca)
        rango = Promo.create({'name': 'Rango', 'bines': '454600-454699, 421301',
                              'porcentaje': 5, 'company_id': self.company.id, 'sequence': 0,
                              'cuenta_id': self.cuenta_descuentos.id})
        self.assertTrue(rango._califica({'iin': '454650'}))
        self.assertTrue(rango._califica({'iin': '42130199'}))
        self.assertFalse(rango._califica({'iin': '454700'}))
        self.assertFalse(rango._califica({}))
        with self.assertRaises(ValidationError):
            rango.bines = '45x6'

    def test_catalogo_vigencia_y_otra_compania(self):
        self.promo_itau.date_to = '2000-01-01'
        self.assertFalse(self.env['getnet.promocion']._buscar(
            {'emisor_id': '12', 'tarjeta_tipo': 'DEB'}, self.company))
        otra = self.env['res.company'].create({'name': 'Otra Promos'})
        self.assertFalse(self.env['getnet.promocion']._vigentes(otra))

    def test_producto_de_descuento_por_defecto_y_cuenta_obligatoria(self):
        promo = self.env['getnet.promocion'].create({
            'name': 'Con defaults', 'porcentaje': 5, 'company_id': self.company.id,
            'cuenta_id': self.cuenta_descuentos.id})
        self.assertEqual(promo.producto_descuento_id, self.env.ref(
            'odoo_pos_getnet_promociones.producto_descuento_promocion'))
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.env['getnet.promocion'].create({
                    'name': 'Sin cuenta', 'porcentaje': 5, 'company_id': self.company.id})

    # ==================================================================
    # B · detección automática
    # ==================================================================
    def test_b_completo_lee_aplica_restringe_y_verifica(self):
        """El camino feliz de B, con un cajero."""
        app = self.env['pos_backend.app'].with_user(self.cajero)
        order = self._pedido()
        self.env.flush_all()
        self.env.invalidate_all()
        r = self._leer(order, VISA_ITAU, app=app)
        self.assertEqual(r['state'], 'ready')
        self.assertAlmostEqual(r['amount'], 900.0)
        self.assertIn('ITAU débito 10', r['message'])
        lectura = self._posteos(supuestos.METODO_POSTEAR)[0]
        self.assertEqual(lectura[supuestos.PARAMETRO_POSTEAR]['MontoTAP'], 100000)
        self.assertNotIn('Monto', lectura[supuestos.PARAMETRO_POSTEAR])
        linea = self._cobrar(order, VISA_ITAU, r['amount'], app=app)
        venta = self._posteos()[0]['Transaccion']
        self.assertEqual(venta['Monto'], 90000)
        self.assertEqual((venta['TarjetaId'], venta['EmisorId'], venta['TarjetaTipo']),
                         (2, 12, 'DEB'))
        self.assertEqual(linea.integration_state, 'autorizado')
        self.assertEqual(self._avisos(order, app), [])
        self.assertIn('aplicada_auto', self._eventos(order))
        # El registro de la lectura no guarda el número de la tarjeta; el BIN sí.
        registro = self.env['getnet.lectura.tarjeta'].search([('order_id', '=', order.id)])
        self.assertNotIn('4213010000001234', registro.respuesta)
        self.assertIn('421301', registro.respuesta)
        self.assertEqual(registro.state, 'leida')

    def test_b_tarjeta_sin_promo_cobra_el_total_sin_restriccion(self):
        order = self._pedido()
        r = self._leer(order, MASTER_BROU)
        self.assertEqual((r['state'], r['amount']), ('ready', 1000.0))
        self._cobrar(order, MASTER_BROU, 1000.0)
        venta = self._posteos()[0]['Transaccion']
        self.assertNotIn('TarjetaId', venta)
        self.assertNotIn('EmisorId', venta)
        self.assertEqual(self._avisos(order), [])
        self.assertIn('sin_promo', self._eventos(order))

    def _fallback(self, guion, esperado):
        order = self._pedido()
        with self._soap(guion):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 1000.0)
            while r['state'] == 'waiting':
                r = self.app.poll_terminal_payment_preparation(order.id, self.metodo.id, r['token'])
        self.assertEqual(r['state'], 'fallback')
        self.assertIn(esperado, r['message'])
        self.assertTrue(order.getnet_promocion_manual)
        self.assertIn('pasa_a_manual', self._eventos(order))
        # El cobro NO queda trabado: el próximo Agregar cobra directo, sin leer.
        self.llamadas = []
        with self._soap({}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 1000.0)
        self.assertEqual((r['state'], self.llamadas), ('ready', []))
        # Y la selección manual queda ofrecida en el medio.
        datos = self.app.get_payment_screen_data(order.id)
        medio = [m for m in datos['payment_methods'] if m['id'] == self.metodo.id][0]
        self.assertIn('Getnet · ITAU débito 10', [o['label'] for o in medio['payment_options']])
        return order

    def test_b_error_del_concentrador_pasa_a_manual(self):
        self._fallback({supuestos.METODO_POSTEAR: [
            {'Resp_CodigoRespuesta': '999', 'Resp_MensajeError': 'HTTP 504 del concentrador'}]},
            '504')

    def test_b_respuesta_malformada_pasa_a_manual(self):
        self._fallback({supuestos.METODO_POSTEAR: [LECTURA_OK],
                        supuestos.METODO_CONSULTAR: [{'Resp_CodigoRespuesta': '0',
                                                      'Resp_TransaccionFinalizada': 'true'}]},
                       'no trae datos')

    def test_b_error_de_lectura_pasa_a_manual(self):
        self._fallback({supuestos.METODO_POSTEAR: [LECTURA_OK],
                        supuestos.METODO_CONSULTAR: [{'Resp_CodigoRespuesta': '1',
                                                      'Resp_MensajeError': 'METODO NO HABILITADO'}]},
                       'METODO NO HABILITADO')

    def test_b_excepcion_pasa_a_manual(self):
        order = self._pedido()

        def explota(prov, metodo, params):
            raise ValueError('campo ajeno al contrato')
        with patch.object(type(self.provider), '_getnet_soap_transaccion', explota):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 1000.0)
        self.assertEqual(r['state'], 'fallback')
        self.assertTrue(order.getnet_promocion_manual)

    def test_b_timeout_pasa_a_manual(self):
        order = self._pedido()
        with self._soap({supuestos.METODO_POSTEAR: [LECTURA_OK]}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 1000.0)
        with patch.object(supuestos, 'LECTURA_TOPE_SEGUNDOS', -1), self._soap({}):
            r = self.app.poll_terminal_payment_preparation(order.id, self.metodo.id, r['token'])
        self.assertEqual(r['state'], 'fallback')
        self.assertIn('a tiempo', r['message'])

    def test_cambio_de_modo_rige_en_el_proximo_cobro(self):
        order = self._pedido()
        self.metodo.getnet_modo_promociones = 'off'
        with self._soap({}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 1000.0)
        self.assertEqual((r['state'], self.llamadas), ('ready', []))
        self.assertEqual(self._avisos(order), [])
        self.metodo.getnet_modo_promociones = 'manual'
        datos = self.app.get_payment_screen_data(order.id)
        medio = [m for m in datos['payment_methods'] if m['id'] == self.metodo.id][0]
        self.assertTrue(medio['payment_options'])

    def test_sin_promociones_cargadas_no_se_lee(self):
        self.env['getnet.promocion'].search([]).write({'active': False})
        order = self._pedido()
        with self._soap({}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 1000.0)
        self.assertEqual((r['state'], self.llamadas), ('ready', []))

    # ==================================================================
    # A · selección manual
    # ==================================================================
    def test_a_completo_elige_restringe_y_verifica(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        r = self.app.apply_terminal_payment_option(
            order.id, self.metodo.id, 'promo_%s' % self.promo_oca.id)
        self.assertIn('OCA 20', r['message'])
        self.assertAlmostEqual(order.amount_total, 800.0)
        oca = {'TarjetaId': '6', 'EmisorId': '14', 'TarjetaTipo': 'CRE', 'TarjetaIIN': '589657'}
        with self._soap({}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 800.0)
        self.assertEqual(r['state'], 'ready')
        self._cobrar(order, oca, 800.0)
        venta = self._posteos()[0]['Transaccion']
        self.assertEqual(venta['EmisorId'], 14)
        self.assertNotIn('TarjetaId', venta)
        self.assertEqual(self._avisos(order), [])
        self.assertIn('aplicada_manual', self._eventos(order))

    def test_a_sin_promocion_borra_solo_su_linea(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido(((1000.0, None), (500.0, None)))
        order.line_ids[0].sudo().with_context(pos_backend_authorized=True).discount = 20
        productos = order.line_ids
        antes = [(l.id, l.price_unit, l.discount) for l in productos]
        self.app.apply_terminal_payment_option(order.id, self.metodo.id,
                                               'promo_%s' % self.promo_itau.id)
        # Las líneas de producto NO cambian: la promo es una línea aparte.
        self.assertEqual([(l.id, l.price_unit, l.discount) for l in productos], antes)
        promo = order.line_ids.filtered('getnet_promocion_id')
        self.assertEqual(len(promo), 1)
        self.assertAlmostEqual(promo.price_unit, -130.0)   # 10 % de 800 + 500
        self.app.apply_terminal_payment_option(order.id, self.metodo.id, 'sin_promo')
        self.assertEqual(order.line_ids, productos)
        self.assertEqual([(l.id, l.price_unit, l.discount) for l in productos], antes)
        self.assertFalse(order.getnet_promocion_id)
        self.assertIn('quitada', self._eventos(order))

    # ==================================================================
    # Pago dividido
    # ==================================================================
    def test_pago_dividido_b_no_lee_y_cobra_sin_promo(self):
        order = self._pedido()
        with self._soap({}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 400.0)
        self.assertEqual((r['state'], r['amount'], self.llamadas), ('ready', 400.0, []))
        self.assertIn('Pago dividido', r['message'])
        self.assertIn('pago_dividido', self._eventos(order))

    def test_pago_dividido_a_no_deja_elegir(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        self.app.add_payment_line(order.id, self.efectivo.id, 300.0)
        with self.assertRaisesRegex(UserError, 'Pago dividido'):
            self.app.apply_terminal_payment_option(
                order.id, self.metodo.id, 'promo_%s' % self.promo_oca.id)

    def test_promo_aplicada_y_cobro_parcial_se_rechaza(self):
        order = self._pedido()
        self._leer(order, VISA_ITAU)
        with self._soap({}):
            r = self.app.prepare_terminal_payment(order.id, self.metodo.id, 500.0)
        self.assertEqual(r['state'], 'rejected')
        self.assertIn('Pago dividido', r['message'])

    def test_promo_aplicada_y_efectivo_bloquea_hasta_quitarla(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        self.app.apply_terminal_payment_option(order.id, self.metodo.id,
                                               'promo_%s' % self.promo_oca.id)
        self.app.add_payment_line(order.id, self.efectivo.id, 800.0)
        avisos = self._avisos(order)
        self.assertTrue(avisos[0]['blocking'])
        with self.assertRaises(UserError):
            self.app.finalize_order(order.id)
        self.app.run_terminal_notice_action(order.id, self.metodo.id, avisos[0]['key'], 'quitar_promo')
        self.assertAlmostEqual(order.amount_total, 1000.0)
        self.assertEqual(self._avisos(order), [])

    # ==================================================================
    # Rechazo
    # ==================================================================
    def test_rechazo_no_cobra_y_la_promo_queda_hasta_quitarla(self):
        order = self._pedido()
        self._leer(order, VISA_ITAU)
        with self.assertRaises(UserError), \
                self._soap({'PostearTransaccion': [POSTEO_OK],
                            'ConsultarTransaccion': [DENEGADA]}), self._reloj():
            self.app.add_payment_line(order.id, self.metodo.id, 900.0)
        self.assertFalse(order.payment_line_ids)
        self.assertEqual(order.getnet_promocion_id, self.promo_itau)
        aviso = self._avisos(order)[0]
        self.assertFalse(aviso['blocking'])
        self.assertEqual([a['key'] for a in aviso['actions']], ['quitar_promo'])
        self.app.run_terminal_notice_action(order.id, self.metodo.id, aviso['key'], 'quitar_promo')
        self.assertAlmostEqual(order.amount_total, 1000.0)

    # ==================================================================
    # Verificación al aprobar
    # ==================================================================
    def test_promo_no_aplicada_seguir_sin_promo(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        linea = self._cobrar(order, VISA_ITAU, 1000.0)
        avisos = self._avisos(order)
        self.assertEqual(len(avisos), 1)
        self.assertIn('PROMO NO APLICADA', avisos[0]['text'])
        self.assertTrue(avisos[0]['blocking'])
        self.assertEqual({a['key'] for a in avisos[0]['actions']},
                         {'seguir_sin_promo', 'reversar_con_promo'})
        with self.assertRaisesRegex(UserError, 'PROMO NO APLICADA'):
            self.app.finalize_order(order.id)
        self.app.run_terminal_notice_action(order.id, self.metodo.id, avisos[0]['key'],
                                            'seguir_sin_promo')
        self.assertEqual(self._avisos(order), [])
        self.assertEqual(linea.integration_state, 'autorizado')
        self.assertFalse(order.getnet_promocion_id)
        self.assertEqual(self._eventos(order).count('no_aplicada'), 1)
        self.assertIn('seguir_sin_promo', self._eventos(order))

    def test_promo_no_aplicada_reversar_y_cobrar_con_promo(self):
        self.metodo.getnet_modo_promociones = 'off'
        order = self._pedido()
        linea = self._cobrar(order, VISA_ITAU, 1000.0)
        self.metodo.getnet_modo_promociones = 'auto'
        aviso = self._avisos(order)[0]
        with self._soap({'PostearTransaccion': [dict(POSTEO_OK, TokenNro='TOK-DEV')],
                         'ConsultarTransaccion': [_aprobada(VISA_ITAU, '7002')]}), self._reloj():
            r = self.app.run_terminal_notice_action(order.id, self.metodo.id, aviso['key'],
                                                    'reversar_con_promo')
        dev = self._posteos()[-1]['Transaccion']
        self.assertEqual((dev['Operacion'], dev['Monto'], dev['TicketOriginal']), ('DEV', 100000, 7001))
        self.assertEqual(linea.integration_state, 'reversado')
        self.assertEqual(order.getnet_promocion_id, self.promo_itau)
        self.assertAlmostEqual(order.amount_total, 900.0)
        self.assertIn('900', r['message'])
        self.assertIn('reversada', self._eventos(order))

    def test_promo_no_coincide_bloquea_y_reversa_sin_promo(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        self.app.apply_terminal_payment_option(order.id, self.metodo.id,
                                               'promo_%s' % self.promo_oca.id)
        # El pinpad debería haberla rechazado (EmisorId=14); si igual pasa
        # otra tarjeta, el POS lo frena.
        linea = self._cobrar(order, VISA_ITAU, 800.0)
        aviso = self._avisos(order)[0]
        self.assertIn('PROMO NO COINCIDE', aviso['text'])
        self.assertTrue(aviso['blocking'])
        self.assertEqual([a['key'] for a in aviso['actions']], ['reversar_sin_promo'])
        with self.assertRaisesRegex(UserError, 'PROMO NO COINCIDE'):
            self.app.finalize_order(order.id)
        with self._soap({'PostearTransaccion': [dict(POSTEO_OK, TokenNro='TOK-DEV')],
                         'ConsultarTransaccion': [_aprobada(VISA_ITAU, '7003')]}), self._reloj():
            self.app.run_terminal_notice_action(order.id, self.metodo.id, aviso['key'],
                                                'reversar_sin_promo')
        self.assertEqual(linea.integration_state, 'reversado')
        self.assertFalse(order.getnet_promocion_id)
        self.assertAlmostEqual(order.amount_total, 1000.0)
        self.assertEqual(self._avisos(order), [])
        eventos = self._eventos(order)
        for evento in ('no_coincide', 'reversada', 'quitada'):
            self.assertIn(evento, eventos)

    def test_la_reversa_que_falla_no_toca_la_promo(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        self.app.apply_terminal_payment_option(order.id, self.metodo.id,
                                               'promo_%s' % self.promo_oca.id)
        self._cobrar(order, VISA_ITAU, 800.0)
        aviso = self._avisos(order)[0]
        with self.assertRaises(UserError), self._soap({'PostearTransaccion': [
                {'Resp_CodigoRespuesta': '2', 'Resp_MensajeError': 'NO'}]}):
            self.app.run_terminal_notice_action(order.id, self.metodo.id, aviso['key'],
                                                'reversar_sin_promo')
        self.assertEqual(order.getnet_promocion_id, self.promo_oca)

    # ==================================================================
    # Quién financia
    # ==================================================================
    def _lineas_de_promo(self, order, promo, esperado):
        """Verifica la regla única: línea aparte, por impuesto, productos intactos."""
        productos = order.line_ids.filtered(lambda l: not l.getnet_promocion_id)
        self.assertEqual(productos.mapped('discount'), [0.0] * len(productos))
        self.assertEqual(productos.mapped('price_unit'), [1000.0, 200.0])
        lineas = order.line_ids.filtered('getnet_promocion_id')
        self.assertEqual(lineas.getnet_promocion_id, promo)
        self.assertTrue(all(lineas.mapped('is_reward_line')))
        self.assertEqual(set(lineas.mapped('description')), {'Promoción %s' % promo.name})
        self.assertEqual({l.tax_ids: round(l.price_unit, 2) for l in lineas}, esperado)
        return lineas

    def _modo_y_financiador(self, modo, promo):
        order = self._pedido(((1000.0, self.iva22), (200.0, self.iva10)))
        tarjeta = VISA_ITAU if promo == self.promo_itau else {
            'TarjetaId': '6', 'EmisorId': '14', 'TarjetaTipo': 'CRE', 'TarjetaIIN': '589657'}
        if modo == 'auto':
            promo.sequence = 0
            if promo == self.promo_oca:
                self.promo_itau.active = False
            self._leer(order, tarjeta)
        else:
            if modo == 'fallback':
                with self._soap({supuestos.METODO_POSTEAR: [{'Resp_CodigoRespuesta': '1'}]}):
                    self.app.prepare_terminal_payment(order.id, self.metodo.id, 1200.0)
            else:
                self.metodo.getnet_modo_promociones = 'manual'
            self.app.apply_terminal_payment_option(order.id, self.metodo.id, 'promo_%s' % promo.id)
        pct = promo.porcentaje / 100
        self._lineas_de_promo(order, promo, {self.iva22: -1000.0 * pct, self.iva10: -200.0 * pct})
        self.assertAlmostEqual(order.amount_total, 1200.0 * (1 - pct))
        return order, tarjeta

    def test_modo_por_financiador_siempre_linea_aparte(self):
        for modo in ('auto', 'fallback', 'manual'):
            for promo in (self.promo_itau, self.promo_oca):
                with self.subTest(modo=modo, financia=promo.financia):
                    # Cada combinación en su savepoint, que se deshace al final.
                    with self.assertRaises(_Deshacer):
                        with self.env.cr.savepoint():
                            self._modo_y_financiador(modo, promo)
                            raise _Deshacer()
                    self.env.invalidate_all()

    def test_cambiar_productos_rehace_la_linea_de_promo(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido(((1000.0, self.iva22), (200.0, self.iva10)))
        self.app.apply_terminal_payment_option(order.id, self.metodo.id,
                                               'promo_%s' % self.promo_itau.id)
        self.env['pos_backend.order.line'].with_user(self.manager).create({
            'order_id': order.id, 'product_id': self.producto_b.id, 'quantity': 1.0,
            'price_unit': 300.0, 'tax_ids': [(6, 0, self.iva22.ids)]})
        lineas = order.line_ids.filtered('getnet_promocion_id')
        self.assertEqual({l.tax_ids: round(l.price_unit, 2) for l in lineas},
                         {self.iva22: -130.0, self.iva10: -20.0})
        self.assertAlmostEqual(order.amount_total, 1350.0)

    def test_la_linea_de_promo_se_ve_con_su_nombre_y_no_se_edita_a_mano(self):
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido(((1000.0, self.iva22), (200.0, self.iva10)))
        self.app.apply_terminal_payment_option(order.id, self.metodo.id,
                                               'promo_%s' % self.promo_itau.id)
        promo = order.line_ids.filtered('getnet_promocion_id')[0]
        self.assertEqual(self.app._get_order_line_data(promo)['product_name'],
                         'Promoción ITAU débito 10')
        for cambio in ({'quantity': 2}, {'price_unit': -1.0}):
            with self.assertRaisesRegex(UserError, 'no se edita a mano'):
                promo.with_user(self.manager).write(cambio)
        with self.assertRaisesRegex(UserError, 'no se edita a mano'):
            promo.with_user(self.manager).unlink()

    def test_financia_empresa_sin_pin_aunque_haya_regla_de_firma(self):
        for operacion in ('descuento_pedido', 'descuento_linea'):
            self.env['pos_backend.authorization.rule'].sudo().create({
                'name': 'Firma %s' % operacion, 'operation': operacion,
                'threshold': 1, 'company_id': self.company.id,
                'authorizer_group_id': self.env.ref('pos_backend.group_pos_supervisor').id,
            })
        order = self._pedido(((1000.0, self.iva22), (200.0, self.iva10)))
        self._leer(order, VISA_ITAU)
        self.assertAlmostEqual(order.amount_total, 1080.0)

    def _finalizar_con_promo(self, promo):
        order, tarjeta = self._modo_y_financiador('manual', promo)
        linea = self._cobrar(order, tarjeta, order.amount_total, ticket='7101')
        self.assertEqual(self._avisos(order), [])
        self.app.finalize_order(order.id)
        self.assertEqual(order.state, 'finalizado')
        return order, linea

    def test_la_promo_llega_al_pedido_de_venta_y_a_la_factura_con_su_cuenta(self):
        for promo, cuenta in ((self.promo_itau, self.cuenta_descuentos),
                              (self.promo_oca, self.cuenta_reintegro)):
            with self.subTest(financia=promo.financia):
                order, _linea = self._finalizar_con_promo(promo)
                self.promo_itau.active = True
                venta = order.sudo().sale_order_id if 'sale_order_id' in order._fields else \
                    self.env['sale.order.line'].sudo().search(
                        [('pos_backend_order_line_id', 'in', order.line_ids.ids)]).order_id
                lineas_venta = venta.order_line.filtered('getnet_promocion_id')
                self.assertEqual(len(lineas_venta), 2)
                self.assertEqual(set(lineas_venta.mapped('getnet_ticket')), {'7101'})
                self.assertEqual(set(lineas_venta.mapped('name')), {'Promoción %s' % promo.name})
                factura = order.sudo().invoice_ids[:1]
                lineas_fac = factura.invoice_line_ids.filtered('getnet_promocion_id')
                self.assertEqual(len(lineas_fac), 2)
                self.assertEqual(lineas_fac.account_id, cuenta)
                self.assertEqual(set(lineas_fac.mapped('getnet_ticket')), {'7101'})
                productos = factura.invoice_line_ids - lineas_fac
                self.assertEqual(productos.mapped('discount'), [0.0, 0.0])
                self.assertAlmostEqual(factura.amount_total, order.amount_total)

    def test_devolucion_descuenta_la_promo_en_proporcion(self):
        order, _linea = self._finalizar_con_promo(self.promo_oca)
        producto_1000 = order.line_ids.filtered(lambda l: l.price_unit == 1000.0)
        promo_lineas = order.line_ids.filtered('getnet_promocion_id')
        self.assertEqual(set(promo_lineas.mapped('qty_returnable')), {0.0})
        with self.assertRaisesRegex(UserError, 'no se devuelve sola'):
            order.with_user(self.manager).action_create_return(
                [{'line_id': promo_lineas[0].id, 'quantity': 1}])
        # La devolución sale del cajón de HOY: la caja del manager, abierta.
        order.session_id.sudo().write({'state': 'open', 'open_user_id': self.manager.id})
        datos = self.app._get_return_line_data(producto_1000)
        self.assertAlmostEqual(datos['unit_refund'], 800.0)
        devolucion = order.with_user(self.manager).action_create_return(
            [{'line_id': producto_1000.id, 'quantity': 1}])
        self.assertAlmostEqual(devolucion.amount_total, -800.0)
        linea_promo = devolucion.line_ids.filtered('getnet_promocion_id')
        self.assertEqual(linea_promo.tax_ids, self.iva22)
        nota = devolucion.sudo()._create_return_invoice()
        self.assertAlmostEqual(nota.amount_total, 800.0)
        self.assertEqual(nota.invoice_line_ids.filtered('getnet_promocion_id').account_id,
                         self.cuenta_reintegro)

    def test_no_aplicada_aunque_el_request_no_vea_el_cobro(self):
        """El request corre en REPEATABLE READ: el cobro que commiteó el cursor
        propio no existe en su foto. La tarjeta se lee en un cursor propio, así
        que el aviso aparece igual. Se simula dejando al env del request sin
        transacciones y al cursor propio con la verdad."""
        self.metodo.getnet_modo_promociones = 'manual'
        order = self._pedido()
        self._cobrar(order, VISA_ITAU, 1000.0)
        Tx = type(self.env['payment.transaction'])
        search_real = Tx.search
        propio = {'activo': False}

        def search_sin_foto(modelo, dominio, *a, **k):
            if not propio['activo'] and any(
                    isinstance(c, tuple) and c[0] == 'getnet_pos_backend_reference' for c in dominio):
                return modelo.browse()
            return search_real(modelo, dominio, *a, **k)

        def cursor_propio(modelo, trabajo):
            propio['activo'] = True
            try:
                return trabajo(self.env)
            finally:
                propio['activo'] = False
        self.patch(Tx, 'search', search_sin_foto)
        self.patch(type(self.env['pos_backend.terminal.getnet']), '_getnet_en_cursor_propio', cursor_propio)
        avisos = self._avisos(order)
        self.assertEqual(len(avisos), 1)
        self.assertIn('PROMO NO APLICADA', avisos[0]['text'])
