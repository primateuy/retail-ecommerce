# -*- coding: utf-8 -*-
"""Importación de agrupadores de precio desde el producto.

🔴 El caso reportado: el archivo carga `x_price_group_line_ids/price_group_id`
sobre product.template y fallaba en TODAS las filas —incluso un archivo recién
exportado— con "Please specify the product for which this rule should be
applied": la línea se creaba sin producto y su regla de precio también.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

CAMPOS = ['id', 'x_price_group_line_ids/price_group_id']


@tagged('post_install', '-at_install', 'price_group_import')
class TestImportacionAgrupador(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.lista = env['product.pricelist'].create({'name': 'Precio 2x prueba'})
        Grupo = env['x_price_group']
        cls.g1200 = Grupo.create({'name': 'Prueba 2x$1.200', 'lista_precio_id': cls.lista.id, 'valor_fijo': 600})
        cls.g1500 = Grupo.create({'name': 'Prueba 2x$1.500', 'lista_precio_id': cls.lista.id, 'valor_fijo': 750})
        PT = env['product.template']
        cls.p_nuevo = PT.create({'name': 'Remera prueba agrupador A'})
        cls.p_mismo = PT.create({'name': 'Remera prueba agrupador B'})
        cls.p_otro = PT.create({'name': 'Remera prueba agrupador C'})
        L = env['x_price_group_line']
        cls.l_mismo = L.create({'product_tmpl_id': cls.p_mismo.id, 'price_group_id': cls.g1200.id})
        cls.l_otro = L.create({'product_tmpl_id': cls.p_otro.id, 'price_group_id': cls.g1200.id})
        # xmlids como los de un archivo exportado
        cls.xid = {p: p._export_rows([['id']])[0][0] for p in (cls.p_nuevo, cls.p_mismo, cls.p_otro)}

    def _importar(self, filas):
        res = self.env['product.template'].with_context(import_file=True).load(CAMPOS, filas)
        self.assertFalse(res['messages'], res['messages'])
        return res

    def _vigentes(self, producto):
        ahora = fields.Datetime.now()
        return producto.x_price_group_line_ids.filtered(
            lambda l: l.activo and (not l.date_start or l.date_start <= ahora)
            and (not l.date_end or l.date_end >= ahora))

    def test_producto_sin_agrupador(self):
        """El caso reportado: ahora importa y la regla de precio tiene producto."""
        self._importar([[self.xid[self.p_nuevo], self.g1200.name]])
        linea = self.p_nuevo.x_price_group_line_ids
        self.assertEqual(len(linea), 1)
        self.assertEqual(linea.product_tmpl_id, self.p_nuevo)
        self.assertEqual(linea.price_group_id, self.g1200)
        item = linea.price_list_item_id
        self.assertEqual((item.applied_on, item.product_tmpl_id, item.fixed_price),
                         ('1_product', self.p_nuevo, 600))

    def test_mismo_agrupador_no_duplica(self):
        items_antes = self.lista.item_ids
        self._importar([[self.xid[self.p_mismo], self.g1200.name]])
        self.assertEqual(self.p_mismo.x_price_group_line_ids, self.l_mismo)
        self.assertEqual(self.lista.item_ids, items_antes)

    def test_otro_agrupador_reemplaza_al_vigente(self):
        self._importar([[self.xid[self.p_otro], self.g1500.name]])
        vigentes = self._vigentes(self.p_otro)
        self.assertEqual(vigentes.price_group_id, self.g1500, "un solo agrupador vigente")
        nueva = vigentes
        self.assertTrue(self.l_otro.date_end, "el anterior queda cerrado, no borrado")
        self.assertLess(self.l_otro.date_end, nueva.date_start)
        self.assertEqual(self.l_otro.price_list_item_id.date_end, self.l_otro.date_end,
                         "su regla de precio deja de aplicar")
        self.assertEqual(nueva.price_list_item_id.fixed_price, 750)

    def test_reimportar_lo_exportado(self):
        """"Exporté y quise importar lo mismo y da error": ahora no cambia nada."""
        productos = self.p_mismo | self.p_otro
        datos = productos.export_data(CAMPOS)['datas']
        lineas_antes = self.env['x_price_group_line'].search([('product_tmpl_relacion_id', 'in', productos.ids)])
        self._importar(datos)
        lineas_despues = self.env['x_price_group_line'].search([('product_tmpl_relacion_id', 'in', productos.ids)])
        self.assertEqual(lineas_despues, lineas_antes)
        self.assertFalse(self.l_mismo.date_end)

    def test_archivo_mezclado(self):
        self._importar([[self.xid[self.p_nuevo], self.g1500.name],
                        [self.xid[self.p_mismo], self.g1200.name],
                        [self.xid[self.p_otro], self.g1500.name]])
        for producto, grupo in ((self.p_nuevo, self.g1500), (self.p_mismo, self.g1200),
                                (self.p_otro, self.g1500)):
            self.assertEqual(self._vigentes(producto).price_group_id, grupo)

    def test_dos_agrupadores_superpuestos_no_se_permiten(self):
        """El control sólo miraba el mismo agrupador. Al crear, el anterior se
        cierra solo; editando fechas a mano ya no se pueden pisar."""
        manana = fields.Datetime.now() + timedelta(days=1)
        self.env['x_price_group_line'].create({
            'product_tmpl_id': self.p_mismo.id, 'price_group_id': self.g1500.id, 'date_start': manana})
        self.assertTrue(self.l_mismo.date_end, "se cerró al programar el nuevo")
        with self.assertRaises(ValidationError):
            self.l_mismo.date_end = False

    def test_fecha_de_inicio_sola_no_revienta(self):
        """date.min contra un Datetime daba TypeError."""
        desde = fields.Datetime.now() + timedelta(days=10)
        linea = self.env['x_price_group_line'].create({
            'product_tmpl_id': self.p_nuevo.id, 'price_group_id': self.g1200.id, 'date_start': desde})
        self.assertEqual(linea.date_start, desde)

    def test_agrupador_programado_a_futuro_avisa(self):
        desde = fields.Datetime.now() + timedelta(days=10)
        self.l_otro.write({'date_start': desde})
        with self.assertRaises(UserError):
            self.env['x_price_group_line'].create({
                'product_tmpl_id': self.p_otro.id, 'price_group_id': self.g1500.id})
