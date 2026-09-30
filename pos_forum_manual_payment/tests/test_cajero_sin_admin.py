# -*- coding: utf-8 -*-
"""El PDV de un cajero sin administrador no abría: «No puede acceder a los
registros 'Modelos' (ir.model)».

El catálogo de campos del popup manual apunta a ir.model (relation_model_id) y
Odoo 17 sólo deja leer ir.model a Administración/Permisos de acceso. Se leía
como el cajero en dos lugares: al armar el popup (carga del PDV) y al resolver
el nombre del sello (sincronización del pedido).
"""
import json
import unittest

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pos_manual_cajero')
class TestCajeroSinAdmin(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.metodo = env['pos.payment.method'].search([
            ('manual_transaction_enabled', '=', True),
            ('manual_provider_id.manual_field_config_ids.request_field_id.field_type', '=', 'many2one'),
        ], limit=1)
        if not cls.metodo:
            raise unittest.SkipTest('No hay método manual con un campo relacional (sello)')
        cls.campo = cls.metodo.manual_provider_id.manual_field_config_ids.request_field_id.filtered(
            lambda f: f.field_type == 'many2one')[:1]
        # El permiso como lo trae Odoo 17: los usuarios internos NO leen ir.model.
        for xmlid in ('base.access_ir_model_user', 'base.access_ir_model_fields_user'):
            env.ref(xmlid).perm_read = False
        compania = cls.metodo.company_id or env.company
        cls.cajero = env['res.users'].create({
            'name': 'Cajero sin admin prueba', 'login': 'cajero_sin_admin_prueba',
            'company_id': compania.id, 'company_ids': [(6, 0, compania.ids)],
            'groups_id': [(6, 0, [env.ref('base.group_user').id,
                                  env.ref('point_of_sale.group_pos_user').id])],
        })

    def test_el_cajero_no_lee_ir_model(self):
        """Condición del caso: si esto no falla, el test no prueba nada."""
        with self.assertRaises(AccessError):
            self.env['ir.model'].with_user(self.cajero).check_access_rights('read')

    def test_el_popup_se_arma_como_cajero(self):
        self.env.invalidate_all()
        metodo = self.metodo.with_user(self.cajero)
        lineas = json.loads(metodo.manual_payment_popup_config)
        sello = [l for l in lineas if l['code'] == self.campo.code]
        self.assertEqual(len(sello), 1)
        self.assertEqual(sello[0]['relation_model'], self.campo.relation_model_id.model)

    def test_el_sello_se_resuelve_como_cajero(self):
        registro = self.env[self.campo.relation_model_id.model].sudo().search([], limit=1)
        if not registro:
            self.skipTest('Sin registros del modelo del sello')
        # Sin cache: si no, el ir.model ya leído como superusuario no se vuelve a chequear.
        self.env.invalidate_all()
        tx = self.env['payment.transaction'].with_user(self.cajero)
        nombre = tx._forum_resolve_reference_label(self.campo.with_user(self.cajero), str(registro.id))
        self.assertEqual(nombre, registro.display_name)
