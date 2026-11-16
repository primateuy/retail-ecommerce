# -*- coding: utf-8 -*-
"""
Crear el pago contable de un cobro OCA desde la transacción (Forum, 2026-11-16).

Cobros aprobados que nunca quedaron en una venta: si no se devuelven, el ingreso
tiene que entrar en contabilidad igual. El pago sale con el diario y el método
del proveedor, el monto del cobro y el cliente que se elige.
"""
import json

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestOcaPagoAsociado(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.diario = cls.env['account.journal'].create({
            'name': 'OCA (test pago asociado)', 'type': 'bank', 'code': 'TOPA',
        })
        cls.proveedor = cls.env['payment.provider'].create({
            'name': 'OCA (test pago asociado)', 'code': 'oca', 'state': 'test',
            'url_webservice': 'https://oca.test/itdServer', 'codigo_sistema': 'SYS-PROV',
            'branch': '1', 'client_app_id': '1',
            'payment_method_ids': [(6, 0, metodo.ids)],
        })
        cls.proveedor.journal_id = cls.diario
        cls.metodo = metodo
        cls.cliente = cls.env['res.partner'].create({'name': 'Cliente del cobro (test)'})
        cls.soporte = new_test_user(
            cls.env, login='soporte_pago_asociado',
            groups='base.group_user,odoo_pos_oca_core.group_oca_reverso',
        )
        cls.cajero = new_test_user(cls.env, login='cajero_pago_asociado', groups='base.group_user')
        cls.admin_contable = new_test_user(
            cls.env, login='admin_contable_pago_asociado', groups='account.group_account_manager',
        )

    def _cobro(self, **extra):
        vals = {
            'amount': 2687.35, 'currency_id': self.env.company.currency_id.id,
            'partner_id': self.env.company.partner_id.id,
            'payment_method_id': self.metodo.id, 'provider_id': self.proveedor.id,
            'reference': 'TEST-PAGO-ASOC-%s' % len(self.env['payment.transaction'].search([])),
            'state': 'done', 'pos_id': '30747668', 'ticket_number': '514',
            'authorization_code': '123456',
            'oca_complete_response': json.dumps({'ResponseCode': '0', 'TransactionType': 'C'}),
        }
        vals.update(extra)
        return self.env['payment.transaction'].sudo().create(vals)

    def _wizard(self, tx, **vals):
        return self.env['oca.pago.asociado.wizard'].with_user(self.soporte).create(
            dict({'transaction_id': tx.id}, **vals),
        )

    def test_crea_el_pago_con_los_datos_del_cobro_y_lo_enlaza(self):
        tx = self._cobro()
        wizard = self._wizard(tx)
        self.assertEqual(wizard.partner_id, tx.partner_id, 'el cliente viene precargado')
        self.assertEqual(wizard.date, fields.Date.context_today(wizard, timestamp=tx.create_date))
        wizard.partner_id = self.cliente
        accion = wizard.action_confirmar()

        pago = self.env['account.payment'].browse(accion['res_id'])
        self.assertEqual(pago.state, 'posted')
        self.assertEqual(pago.payment_type, 'inbound')
        self.assertEqual(pago.partner_type, 'customer')
        self.assertEqual(pago.partner_id, self.cliente)
        self.assertEqual(pago.amount, 2687.35)
        self.assertEqual(pago.currency_id, tx.currency_id)
        self.assertEqual(pago.journal_id, self.diario)
        self.assertEqual(pago.payment_method_line_id, tx._oca_linea_metodo_pago_asociado())
        self.assertEqual(pago.payment_method_line_id.journal_id, self.diario)
        self.assertIn('514', pago.ref)
        self.assertEqual(pago.payment_transaction_id, tx)
        self.assertEqual(tx.payment_id, pago)

    def test_la_linea_es_la_del_proveedor(self):
        tx = self._cobro()
        linea = tx._oca_linea_metodo_pago_asociado()
        self.assertEqual(linea.payment_provider_id, self.proveedor)

    def test_un_cobro_con_pago_no_se_duplica(self):
        tx = self._cobro()
        self._wizard(tx, partner_id=self.cliente.id).action_confirmar()
        self.assertIn('ya tiene el pago', tx._oca_motivo_sin_pago_asociado())
        with self.assertRaises(UserError):
            tx.with_user(self.soporte).action_oca_crear_pago_asociado()
        with self.assertRaises(UserError):
            tx.with_user(self.soporte)._oca_crear_pago_asociado(self.cliente, fields.Date.today())

    def test_no_se_crea_para_lo_que_no_es_un_cobro_aprobado(self):
        self.assertTrue(self._cobro(state='error')._oca_motivo_sin_pago_asociado())
        anulacion = self._cobro(
            oca_complete_response=json.dumps({'ResponseCode': '0', 'TransactionType': 'A'}),
        )
        self.assertTrue(anulacion._oca_motivo_sin_pago_asociado())
        original = self._cobro()
        reverso = self._cobro(oca_reverso_de_id=original.id)
        self.assertTrue(reverso._oca_motivo_sin_pago_asociado())
        self.assertIn('anulado o devuelto', original._oca_motivo_sin_pago_asociado())

    def test_sin_el_grupo_no_se_puede(self):
        tx = self._cobro()
        for usuario in (self.cajero, self.admin_contable):
            with self.assertRaises(AccessError):
                tx.with_user(usuario).action_oca_crear_pago_asociado()
            with self.assertRaises(AccessError):
                tx.with_user(usuario)._oca_crear_pago_asociado(self.cliente, fields.Date.today())
        self.assertFalse(tx.payment_id)

    def test_boton_visible_en_toda_transaccion_oca(self):
        arch = self.env['payment.transaction'].with_user(self.soporte).get_views(
            [(False, 'form')],
        )['views']['form']['arch']
        self.assertIn('action_oca_crear_pago_asociado', arch)
        arch_cajero = self.env['payment.transaction'].with_user(self.admin_contable).get_views(
            [(False, 'form')],
        )['views']['form']['arch']
        self.assertNotIn('action_oca_crear_pago_asociado', arch_cajero)