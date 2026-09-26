# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBranchAnchor(TransactionCase):
    """El ancla de sucursal y la sincronización de compañías."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.casa_central = cls.env['res.company'].create({'name': 'Casa Central Test'})
        cls.franquicia = cls.env['res.company'].create({
            'name': 'Franquicia Test',
            'parent_id': cls.casa_central.id,
        })
        # El almacén del local es de la casa central: es el caso franquicia.
        cls.warehouse = cls.env['stock.warehouse'].create({
            'name': 'Local Test',
            'code': 'LTST',
            'company_id': cls.casa_central.id,
            'is_branch': True,
        })
        # Un pos.config en una compania nueva hereda diarios y metodos de pago de
        # otra compania y _check_company los rechaza. Se le crean los propios.
        cls.journal_pos = cls.env['account.journal'].create({
            'name': 'PDV Test', 'type': 'general', 'code': 'PDVT',
            'company_id': cls.franquicia.id,
        })
        cls.journal_venta = cls.env['account.journal'].create({
            'name': 'Ventas Test', 'type': 'sale', 'code': 'VTAT',
            'company_id': cls.franquicia.id,
        })
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'PDV Local Test',
            'company_id': cls.franquicia.id,
            'payment_method_ids': [(5, 0, 0)],
            'journal_id': cls.journal_pos.id,
            'invoice_journal_id': cls.journal_venta.id,
        })
        cls.user = cls.env['res.users'].create({
            'name': 'Usuario Local Test',
            'login': 'usuario.local.test',
            'company_id': cls.franquicia.id,
            'company_ids': [(6, 0, [cls.franquicia.id])],
        })

    def test_compania_de_facturacion_sale_del_pdv(self):
        self.warehouse.branch_pos_config_ids = self.pos_config
        self.assertEqual(self.warehouse.branch_pos_company_id, self.franquicia)

    def test_dos_companias_de_pdv_es_error(self):
        journal = self.env['account.journal'].create({
            'name': 'PDV CC', 'type': 'general', 'code': 'PDVC',
            'company_id': self.casa_central.id,
        })
        otro_pos = self.env['pos.config'].create({
            'name': 'PDV Otra Compañía',
            'company_id': self.casa_central.id,
            'payment_method_ids': [(5, 0, 0)],
            'journal_id': journal.id,
            'invoice_journal_id': False,
        })
        with self.assertRaises(ValidationError):
            self.warehouse.branch_pos_config_ids = self.pos_config | otro_pos

    def test_asignar_sucursal_agrega_la_compania_del_almacen(self):
        """El caso que justifica todo el módulo.

        El usuario es de la franquicia; el almacén, de la casa central. Sin la compañía
        de la casa central en company_ids no podría ver su propio almacén, porque las
        reglas de stock usan 'in company_ids' y no jerarquía.
        """
        self.warehouse.branch_pos_config_ids = self.pos_config
        self.assertNotIn(self.casa_central, self.user.company_ids)

        self.user.branch_warehouse_ids = self.warehouse

        self.assertIn(self.casa_central, self.user.company_ids)
        self.assertIn(self.franquicia, self.user.company_ids)

    def test_la_sincronizacion_nunca_quita_companias(self):
        otra = self.env['res.company'].create({'name': 'Otra Compañía Test'})
        self.user.company_ids = [(4, otra.id)]

        self.user.branch_warehouse_ids = self.warehouse
        self.user._sync_branch_companies()

        self.assertIn(otra, self.user.company_ids,
                      'La sincronización quitó una compañía que ya tenía el usuario.')

    def test_asignar_desde_el_almacen_tambien_sincroniza(self):
        self.warehouse.branch_pos_config_ids = self.pos_config
        self.warehouse.branch_user_ids = self.user
        self.assertIn(self.casa_central, self.user.company_ids)

    def test_el_inverso_apunta_a_lo_mismo(self):
        self.user.branch_warehouse_ids = self.warehouse
        self.assertIn(self.user, self.warehouse.branch_user_ids)
        self.assertEqual(self.user._branch_warehouse_ids(), [self.warehouse.id])
