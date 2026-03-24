# -*- coding: utf-8 -*-
"""
Extensión de pos.payment para almacenar datos de transacción manual POS.

Los valores capturados en el popup del POS se serializan en JSON para
trazabilidad y uso posterior al crear payment.transaction.
"""

import json

from odoo import fields, models


class PosPayment(models.Model):
    """
    Agrega al pago POS el JSON de valores de transacción manual.

    El frontend envía manual_payment_values en la línea de pago; se persiste
    aquí para no perder la configuración capturada en el popup.
    """

    _inherit = "pos.payment"

    manual_payment_values_json = fields.Text(
        string="Valores transacción manual (JSON)",
        help="Datos capturados en el popup de transacción manual del POS.",
    )

    def _export_for_ui(self, payment):
        """
        Incluye los valores manuales al reexportar el pago hacia el POS.

        Permite rehidratar información si el flujo lo requiere.
        """
        result = super()._export_for_ui(payment)
        if payment.manual_payment_values_json:
            try:
                result["manual_payment_values"] = json.loads(
                    payment.manual_payment_values_json
                )
            except (ValueError, TypeError):
                result["manual_payment_values"] = {}
        return result
