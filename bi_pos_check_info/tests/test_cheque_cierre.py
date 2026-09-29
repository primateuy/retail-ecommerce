# -*- coding: utf-8 -*-
"""Cheques cargados en el PDV: al cerrar la caja se crea el cheque de terceros.

🔴 El caso que no andaba: el método de pago está sobre un diario de cheques de
terceros, que en l10n_latam_check es de tipo EFECTIVO. Odoo cerraba la caja por
el camino del efectivo y nunca creaba el cheque.
"""
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pos_cheque')
class TestChequeCierre(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.diario = env['account.journal'].search([
            ('type', '=', 'cash'), ('company_id', '=', env.company.id),
            ('outbound_payment_method_line_ids', '!=', False)], limit=0).filtered(
            lambda j: j._get_available_payment_method_lines('inbound').filtered(
                lambda l: l.code == 'new_third_party_checks'))[:1]
        if not cls.diario:
            cls.skipTest(cls, "No hay diario de cheques de terceros en la compañía")
        cls.diario.allow_check_info = True
        # Efectivo propio: un método con arqueo no se puede compartir entre cajas.
        diario_efectivo = env['account.journal'].create({
            'name': 'Efectivo prueba cheques', 'type': 'cash', 'code': 'EPCHQ',
            'company_id': env.company.id})
        cls.efectivo = env['pos.payment.method'].create({
            'name': 'Efectivo prueba cheques', 'journal_id': diario_efectivo.id,
            'company_id': env.company.id})
        cls.metodo = env['pos.payment.method'].create({
            'name': 'Cheque prueba', 'journal_id': cls.diario.id, 'company_id': env.company.id})
        cls.config = env['pos.config'].create({
            'name': 'Caja cheques prueba', 'allow_check_info': True,
            'payment_method_ids': [(6, 0, (cls.metodo | cls.efectivo).ids)]})
        cls.producto = env['product.product'].create({
            'name': 'Producto cheque prueba', 'type': 'consu', 'available_in_pos': True,
            'list_price': 1000, 'taxes_id': [(6, 0, [])]})
        cls.cliente = env['res.partner'].create({'name': 'Cliente cheque prueba', 'vat': '12345672'})
        cls.banco = env['res.bank'].create({'name': 'Banco prueba cheques'})

    def _sesion(self):
        sesion = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        if sesion.state == 'opening_control':
            sesion.action_pos_session_open()
        return sesion

    def _vender(self, sesion, pagos, cliente=True, n=1):
        uid = '98765-%03d-%04d' % (sesion.id % 1000, n)
        ahora = fields.Datetime.to_string(fields.Datetime.now())
        total = sum(p['amount'] for p in pagos)
        orden = {'id': uid, 'to_invoice': False, 'data': {
            'name': 'Orden ' + uid, 'uid': uid, 'sequence_number': n, 'date_order': ahora,
            'creation_date': ahora, 'pos_session_id': sesion.id, 'user_id': self.env.uid,
            'partner_id': self.cliente.id if cliente else False,
            'pricelist_id': self.config.pricelist_id.id, 'fiscal_position_id': False,
            'to_invoice': False, 'amount_paid': total, 'amount_total': total, 'amount_tax': 0,
            'amount_return': 0,
            'lines': [[0, 0, {'product_id': self.producto.id, 'qty': 1, 'price_unit': total,
                              'discount': 0, 'price_subtotal': total, 'price_subtotal_incl': total,
                              'tax_ids': [[6, 0, []]]}]],
            'statement_ids': [[0, 0, dict(p, name=ahora)] for p in pagos],
        }}
        res = self.env['pos.order'].create_from_ui([orden])
        return self.env['pos.order'].browse(res[0]['id'])

    def _pago_cheque(self, monto=1000, banco=True, numero='10001'):
        return {'payment_method_id': self.metodo.id, 'amount': monto, 'check_number': numero,
                'owner_name': 'Juan Pérez', 'bank_account': '001-222',
                'bank_name': self.banco.id if banco else False}

    def _lineas_de_venta(self, sesion, diario):
        """Líneas de extracto de las ventas, sin la de diferencia de arqueo (el
        test cierra sin contar el efectivo)."""
        return self.env['account.bank.statement.line'].search([
            ('pos_session_id', '=', sesion.id), ('journal_id', '=', diario.id),
            ('payment_ref', 'not ilike', 'Cash difference')])

    def _cheques(self, sesion):
        # Por método y diario: `pos_session_id` en account.payment no está
        # guardado en esta base (odoo_pos_oca lo redefine) y no filtra.
        return self.env['account.payment'].search([
            ('pos_payment_method_id', '=', self.metodo.id), ('journal_id', '=', self.diario.id)])

    def test_al_cerrar_la_caja_se_crea_el_cheque(self):
        sesion = self._sesion()
        orden = self._vender(sesion, [self._pago_cheque(monto=1500)])
        self.assertEqual(orden.payment_ids.check_number, '10001', "el PDV guardó el cheque")
        sesion.action_pos_session_closing_control()
        self.assertEqual(sesion.state, 'closed')
        cheque = self._cheques(sesion)
        self.assertEqual(len(cheque), 1)
        self.assertEqual(cheque.payment_method_line_id.code, 'new_third_party_checks')
        self.assertEqual(cheque.check_number, '10001')
        self.assertEqual(cheque.l10n_latam_check_bank_id, self.banco)
        self.assertEqual(cheque.l10n_latam_check_issuer_vat, '12345672')
        self.assertEqual(cheque.amount, 1500)
        self.assertEqual(cheque.state, 'posted')
        self.assertFalse(self._lineas_de_venta(sesion, self.diario),
                         "el cheque no va además como efectivo")

    def test_un_cheque_por_pago_y_el_efectivo_no_cambia(self):
        sesion = self._sesion()
        self._vender(sesion, [self._pago_cheque(monto=700, numero='20001'),
                              {'payment_method_id': self.efectivo.id, 'amount': 300}], n=1)
        self._vender(sesion, [self._pago_cheque(monto=400, numero='20002')], n=2)
        sesion.action_pos_session_closing_control()
        cheques = self._cheques(sesion)
        self.assertEqual(sorted(cheques.mapped('check_number')), ['20001', '20002'])
        self.assertEqual(sum(cheques.mapped('amount')), 1100)
        efectivo = self._lineas_de_venta(sesion, self.efectivo.journal_id)
        self.assertEqual(sum(efectivo.mapped('amount')), 300, "el efectivo sigue igual")

    def test_sin_banco_igual_se_guardan_los_datos(self):
        """Antes `int(None)` hacía fallar todo y el pago quedaba sin cheque."""
        sesion = self._sesion()
        orden = self._vender(sesion, [self._pago_cheque(banco=False)])
        self.assertEqual(orden.payment_ids.check_number, '10001')
        self.assertFalse(orden.payment_ids.bank_id)
        sesion.action_pos_session_closing_control()
        self.assertEqual(len(self._cheques(sesion)), 1)

    def test_sin_cliente_no_traba_el_cierre(self):
        sesion = self._sesion()
        self._vender(sesion, [self._pago_cheque()], cliente=False)
        sesion.action_pos_session_closing_control()
        self.assertEqual(sesion.state, 'closed', "la caja cierra igual")
        self.assertFalse(self._cheques(sesion), "sin cliente no hay cheque de terceros")

    def test_numero_no_numerico_no_traba_el_cierre(self):
        """l10n_latam_check sólo acepta dígitos: con otro número, crear el cheque
        hacía fallar el cierre de toda la caja."""
        sesion = self._sesion()
        self._vender(sesion, [self._pago_cheque(numero='CH-12')])
        sesion.action_pos_session_closing_control()
        self.assertEqual(sesion.state, 'closed')
        self.assertFalse(self._cheques(sesion))
