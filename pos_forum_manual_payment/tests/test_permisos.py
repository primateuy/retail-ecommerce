# -*- coding: utf-8 -*-
"""Permisos del módulo: antes eran GLOBALES (sin grupo), o sea para cualquier
usuario, incluidos portal y público: payment.provider se podía leer, escribir y
crear, y el catálogo de campos manuales, hasta borrar.

Ahora: los internos leen (el cajero lo necesita al registrar la transacción
manual) y sólo Ajustes modifica. payment.transaction y pos.payment.method ya
tienen sus permisos en otros módulos y acá no se agrega nada.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

MODELOS_CATALOGO = ('manual.payment.request.field', 'manual.payment.field.config')


@tagged('post_install', '-at_install', 'pos_manual_permisos')
class TestPermisos(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.portal = Users.create({
            'name': 'Portal permisos prueba', 'login': 'portal_permisos_prueba',
            'groups_id': [(6, 0, [cls.env.ref('base.group_portal').id])]})
        cls.cajero = Users.create({
            'name': 'Cajero permisos prueba', 'login': 'cajero_permisos_prueba',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref('point_of_sale.group_pos_user').id])]})
        cls.admin = Users.create({
            'name': 'Admin permisos prueba', 'login': 'admin_permisos_prueba',
            'groups_id': [(6, 0, [cls.env.ref('base.group_system').id])]})

    def _puede(self, usuario, modelo, operacion):
        return self.env[modelo].with_user(usuario).check_access_rights(operacion, raise_exception=False)

    def test_no_quedan_permisos_globales(self):
        globales = self.env['ir.model.access'].search([
            ('group_id', '=', False),
            ('id', 'in', self.env['ir.model.data'].search([
                ('module', '=', 'pos_forum_manual_payment'),
                ('model', '=', 'ir.model.access')]).mapped('res_id'))])
        self.assertFalse(globales, globales.mapped('name'))

    def test_portal_no_ve_proveedores_ni_catalogo(self):
        for modelo in ('payment.provider',) + MODELOS_CATALOGO:
            self.assertFalse(self._puede(self.portal, modelo, 'read'), modelo)
            self.assertFalse(self._puede(self.portal, modelo, 'write'), modelo)

    def test_portal_no_ve_transacciones_ni_metodos_del_pdv(self):
        self.assertFalse(self._puede(self.portal, 'payment.transaction', 'read'))
        self.assertFalse(self._puede(self.portal, 'pos.payment.method', 'write'))

    def test_el_cajero_lee_pero_no_modifica(self):
        for modelo in ('payment.provider',) + MODELOS_CATALOGO:
            self.assertTrue(self._puede(self.cajero, modelo, 'read'), modelo)
            for op in ('write', 'create', 'unlink'):
                self.assertFalse(self._puede(self.cajero, modelo, op), (modelo, op))

    def test_ajustes_configura_el_catalogo(self):
        for modelo in MODELOS_CATALOGO:
            for op in ('read', 'write', 'create', 'unlink'):
                self.assertTrue(self._puede(self.admin, modelo, op), (modelo, op))
