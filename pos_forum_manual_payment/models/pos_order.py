# -*- coding: utf-8 -*-
"""
Extensión de pos.order para propagar datos de transacción manual al pos.payment.
"""

import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extiende la creación de pagos POS con campos de transacción manual.
    """

    _inherit = "pos.order"

    @api.model
    def _process_order(self, order, draft, existing_order):
        """
        Tras crear/actualizar el pedido y sus pagos, genera payment.transaction
        para líneas con método manual y JSON de popup (pedido validado, no borrador).
        """
        order_id = super()._process_order(order, draft, existing_order)
        if not draft:
            pos_order = self.browse(order_id)
            _logger.info(
                "FORUM manual POS: post-proceso transacciones pedido id=%s nombre=%s pagos=%s.",
                pos_order.id,
                pos_order.name,
                len(pos_order.payment_ids),
            )
            pos_order._forum_create_manual_payment_transactions()
            _logger.info(
                "FORUM manual POS: finalizado post-proceso transacciones pedido id=%s.",
                pos_order.id,
            )
        return order_id

    def _forum_create_manual_payment_transactions(self):
        """
        Invoca la creación de transacciones manuales por cada pago elegible.

        Si falta JSON o configuración, forum_create_manual_transaction_from_pos_payment
        lanza ValidationError y se revierte el pedido (coherente con obligatoriedad en POS).
        """
        self.ensure_one()
        tx_model = self.env["payment.transaction"]
        for payment in self.payment_ids:
            _logger.debug(
                "FORUM manual POS: procesando pos.payment id=%s monto=%s método=%s "
                "manual_tx=%s cambio=%s.",
                payment.id,
                payment.amount,
                payment.payment_method_id.display_name,
                payment.payment_method_id.manual_transaction_enabled,
                payment.is_change,
            )
            tx_model.forum_create_manual_transaction_from_pos_payment(payment)

    @api.model
    def _payment_fields(self, order, ui_paymentline):
        """
        Agrega el JSON de valores manuales al crear pos.payment.

        El diccionario proviene de export_as_JSON de la línea de pago en POS.
        """
        vals = super()._payment_fields(order, ui_paymentline)
        manual_values = ui_paymentline.get("manual_payment_values")
        if manual_values:
            vals["manual_payment_values_json"] = json.dumps(manual_values)
            _logger.debug(
                "FORUM manual POS: _payment_fields incluye manual para pedido %s "
                "claves=%s.",
                order.name,
                sorted(manual_values.keys()),
            )
        return vals
