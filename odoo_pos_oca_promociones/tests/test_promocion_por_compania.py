# -*- coding: utf-8 -*-
"""
Cada compañía aplica su propia promoción OCA (Forum, 2026-10-15).

La promoción se buscaba con ``env.company``. El cobro se procesa en un hilo de superusuario sin
compañía de la caja, donde ``env.company`` es la principal: las cajas de Faringol, Aweryl,
Matias Coore, etc. aplicaban la promoción de Surf. Ahora se elige por el proveedor OCA del
método de pago de la caja.
"""
import importlib.util
import os

from odoo import SUPERUSER_ID, api
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPromocionPorCompania(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        metodo_oca = cls.env['payment.method'].with_context(active_test=False).search(
            [('code', '=', 'oca')], limit=1,
        )
        cls.empresa_a = cls.env.company
        cls.empresa_b = cls.env['res.company'].create({'name': 'RUT B (test promo)'})
        Provider = cls.env['payment.provider']
        comunes = {'code': 'oca', 'state': 'test', 'payment_method_ids': [(6, 0, metodo_oca.ids)]}
        cls.prov_a = Provider.create(dict(comunes, name='OCA A (test promo)', company_id=cls.empresa_a.id))
        cls.prov_b = Provider.create(dict(comunes, name='OCA B (test promo)', company_id=cls.empresa_b.id))
        cls.terminal_b = cls.env['multiple.pos.config'].create({
            'name': 'Caja B (test promo)', 'codigo_terminal': '90000088',
            'payment_provider_id': cls.prov_b.id,
        })
        producto = cls.env['product.product'].create({'name': 'Descuento (test promo)', 'type': 'service'})
        Promocion = cls.env['payment.method.promotion']
        base = {'discount_product_id': producto.id, 'discount_percent': 20.0,
                'require_bin_validation': True, 'bin_ids': [(0, 0, {'name': '542991'})]}
        # La de A va primero por secuencia: es la que el código viejo encontraba siempre.
        cls.promo_a = Promocion.create(dict(base, name='Promo A', sequence=1,
                                            payment_provider_id=cls.prov_a.id, company_id=cls.empresa_a.id))
        cls.promo_b = Promocion.create(dict(base, name='Promo B', sequence=2,
                                            payment_provider_id=cls.prov_b.id, company_id=cls.empresa_b.id))
        Metodo = cls.env['pos.payment.method']
        cls.metodo_a = Metodo.create({'name': 'OCA caja A', 'use_payment_terminal': 'oca',
                                      'payment_provider': cls.prov_a.id, 'company_id': cls.empresa_a.id})
        cls.metodo_b = Metodo.create({'name': 'OCA caja B', 'use_payment_terminal': 'oca',
                                      'payment_provider': cls.prov_b.id, 'company_id': cls.empresa_b.id})
        cls.tarjeta = {'Acquirer': 5, 'Issuer': 21, 'CardNumber': '542991******8034'}

    def _buscar(self, metodo, env=None):
        env = env or self.env
        return env['payment.method.promotion'].find_applicable_promotion(
            card_data=self.tarjeta, provider_code='oca', payment_method_id=metodo.id)

    def _env_del_hilo(self):
        """Como el hilo del pinpad: superusuario, sin compañía de la caja."""
        return api.Environment(self.env.cr, SUPERUSER_ID, {})

    def test_el_hilo_aplica_la_promocion_de_la_caja_de_b(self):
        env = self._env_del_hilo()
        self.assertEqual(env.company, self.env.ref('base.main_company'))
        self.assertEqual(self._buscar(self.metodo_b, env), self.promo_b)

    def test_la_caja_de_a_aplica_la_de_a(self):
        self.assertEqual(self._buscar(self.metodo_a, self._env_del_hilo()), self.promo_a)

    def test_sin_proveedor_en_el_metodo_usa_el_de_la_terminal(self):
        self.metodo_b.write({'payment_provider': False, 'codigo_terminal': '90000088'})
        self.assertEqual(self._buscar(self.metodo_b, self._env_del_hilo()), self.promo_b)

    def test_compania_sin_promocion_activa_no_aplica_ninguna(self):
        self.promo_b.active = False
        self.assertFalse(self._buscar(self.metodo_b, self._env_del_hilo()))
        dominio = self.env['payment.method.promotion']._promotion_domain(self.metodo_b)
        self.assertFalse(self.env['payment.method.promotion'].search(dominio))

    def _tx(self, referencia, proveedor, promocion):
        return self.env['payment.transaction'].sudo().create({
            'amount': 100, 'currency_id': self.env.ref('base.UYU').id,
            'partner_id': self.env.user.partner_id.id,
            'payment_method_id': proveedor.payment_method_ids[:1].id,
            'reference': referencia, 'provider_id': proveedor.id,
            'oca_promotion_id': promocion.id, 'is_promotion': True,
        })

    def _migrar(self):
        self.env.flush_all()
        ruta = os.path.join(os.path.dirname(__file__), '..', 'migrations', '17.0.2.4.0', 'post-migration.py')
        spec = importlib.util.spec_from_file_location('migracion_por_compania', ruta)
        migracion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migracion)
        migracion.migrate(self.env.cr, '17.0.2.3.0')
        self.env.invalidate_all()

    def test_la_migracion_reasigna_a_la_promocion_del_proveedor(self):
        de_b = self._tx('TEST-PROMO-B-1', self.prov_b, self.promo_a)
        de_a = self._tx('TEST-PROMO-A-1', self.prov_a, self.promo_a)
        self._migrar()
        self.assertEqual(de_b.oca_promotion_id, self.promo_b)
        self.assertEqual(de_a.oca_promotion_id, self.promo_a)

    def test_la_migracion_no_reasigna_si_el_proveedor_tiene_dos_promociones(self):
        self.promo_b.copy({'name': 'Promo B bis'})
        de_b = self._tx('TEST-PROMO-B-2', self.prov_b, self.promo_a)
        self._migrar()
        self.assertEqual(de_b.oca_promotion_id, self.promo_a)
