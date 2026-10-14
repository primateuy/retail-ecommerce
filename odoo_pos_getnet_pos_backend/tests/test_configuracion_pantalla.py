# -*- coding: utf-8 -*-
"""
Configurar el medio Getnet POR LA PANTALLA, como lo hace quien implanta.

Las otras suites crean los medios por código, con `terminal_provider` ya
puesto, y por eso no vieron lo que vio Campera en su staging (13/10/2026): en
la lista de medios de la caja el «Proveedor de terminal» sólo se mostraba con
el comportamiento «integrado», y el comportamiento —de solo lectura— sólo se
vuelve «integrado» CON un proveedor. Con un diario Banco el medio quedaba en
«transferencia» y la celda del proveedor nunca aparecía: no había forma de
elegir Getnet.

`Form` respeta los `invisible` y `readonly` de la vista, así que escribir en
un campo oculto falla igual que en el navegador.
"""

from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConfiguracionPorPantalla(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        provider = cls.env['payment.provider'].create({
            'name': 'Getnet Pantalla',
            'code': 'getnet',
            'state': 'test',
        })
        cls.terminal = cls.env['getnet.pos.terminal'].create({
            'name': 'Pinpad Pantalla', 'term_cod': 'T00021',
            'payment_provider_id': provider.id,
        })
        local = cls.env['pos_backend.local'].create({'name': 'Local Pantalla'})
        cls.box = cls.env['pos_backend.box'].create(
            {'name': 'Caja Pantalla', 'local_id': local.id})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Tarjetas Pantalla', 'type': 'bank', 'code': 'TAPAN',
            'company_id': cls.box.company_id.id,
        })

    def test_medio_getnet_se_configura_desde_la_caja(self):
        """Diario Banco → se puede elegir Getnet → la terminal → integrado."""
        with Form(self.box) as caja:
            with caja.payment_method_ids.new() as medio:
                medio.name = 'Tarjetas Getnet'
                medio.journal_id = self.journal
                self.assertEqual(medio.payment_type, 'transferencia')
                medio.terminal_provider = 'getnet'
                self.assertEqual(medio.payment_type, 'integrado')
                medio.getnet_terminal_id = self.terminal
        nuevo = self.box.payment_method_ids.filtered(
            lambda m: m.name == 'Tarjetas Getnet')
        self.assertEqual(nuevo.payment_type, 'integrado')
        self.assertEqual(nuevo.terminal_provider, 'getnet')
        self.assertEqual(nuevo.getnet_terminal_id, self.terminal)

    def test_efectivo_no_ofrece_proveedor_de_terminal(self):
        """El efectivo sigue sin mostrar el proveedor: no hay pinpad en un cajón."""
        cash = self.env['account.journal'].create({
            'name': 'Caja Pantalla', 'type': 'cash', 'code': 'CJPAN',
            'company_id': self.box.company_id.id,
        })
        with Form(self.box) as caja:
            with caja.payment_method_ids.new() as medio:
                medio.name = 'Efectivo Pantalla'
                medio.journal_id = cash
                self.assertEqual(medio.payment_type, 'efectivo')
                with self.assertRaises(AssertionError):
                    medio.terminal_provider = 'getnet'
