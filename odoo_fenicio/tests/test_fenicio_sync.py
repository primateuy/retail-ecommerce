# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase


RAW_ORDER = {
    "idOrden": 1001,
    "numeroOrden": "ORD-1001",
    "referencia": "REF-X",
    "estado": "CONFIRMADA",
    "origen": "WEB",
    "fechaInicio": "2024-03-01T10:00:00",
    "fechaFin": None,
    "comprador": {
        "email": "test@test.com",
        "nombre": "Juan",
        "apellido": "Pérez",
        "telefono": "099000001",
    },
    "pago": {"fechaPago": "2024-03-01T10:05:00", "importe": 1500.0, "estado": "PAGADO"},
    "entrega": {"estado": "AGUARDANDO_DESPACHO", "tipo": "ENVIO"},
    "moneda": "UYU",
    "importeTotal": 1500.0,
}


class TestFenicioSync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.sync = self.env["fenicio.sync"]

    def test_create_order_from_raw(self):
        record = self.sync._update_or_create_order(RAW_ORDER)
        self.assertEqual(record.id_fenicio, 1001)
        self.assertEqual(record.numero_orden, "ORD-1001")
        self.assertEqual(record.comprador_email, "test@test.com")
        self.assertEqual(record.comprador_nombre, "Juan Pérez")
        self.assertEqual(record.estado_entrega, "AGUARDANDO_DESPACHO")
        self.assertAlmostEqual(record.importe_total, 1500.0)

    def test_update_existing_order(self):
        self.sync._update_or_create_order(RAW_ORDER)
        self.sync._update_or_create_order(dict(RAW_ORDER, estado="CANCELADA"))

        records = self.env["fenicio.order"].search([("id_fenicio", "=", 1001)])
        self.assertEqual(len(records), 1)
        self.assertEqual(records.estado, "CANCELADA")

    def test_skip_order_without_id(self):
        self.assertIsNone(self.sync._update_or_create_order({"numeroOrden": "sin-id"}))

    def test_skip_empty_order(self):
        self.assertIsNone(self.sync._update_or_create_order({}))

    def test_sync_orders_persists_all_records(self):
        orders = [dict(RAW_ORDER, idOrden=2000 + i, numeroOrden=f"ORD-{2000+i}") for i in range(5)]

        with patch.object(
            type(self.env["fenicio.client"]),
            "get_all_orders",
            return_value=iter(orders),
        ):
            synced, errors = self.sync._sync_orders()

        self.assertEqual(synced, 5)
        self.assertEqual(errors, 0)
        self.assertEqual(
            self.env["fenicio.order"].search_count([("id_fenicio", ">=", 2000)]), 5
        )
