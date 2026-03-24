# -*- coding: utf-8 -*-
"""
Extensión de payment.provider para pagos manuales en POS.

Este modelo agrega banderas y configuraciones específicas para definir
proveedores de pago que se utilizarán en el flujo de transacciones manuales
del Punto de Venta, permitiendo:
- Asociar diarios.
- Restringir por POS.
- Definir campos adicionales que se deberán completar en el POS.
"""

from odoo import fields, models


class PaymentProvider(models.Model):
    """
    Extensión del modelo payment.provider para pagos manuales POS.

    Esta clase agrega campos de configuración que permiten marcar un proveedor
    como apto para ser utilizado en flujos de pago manual desde el POS, así
    como relacionar diarios, POS y plantillas de campos adicionales que se
    completarán al momento de registrar el pago en el Punto de Venta.
    """

    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("forum_manual", "FORUM Manual POS")],
        ondelete={"forum_manual": "set default"},
    )

    manual_pos_provider = fields.Boolean(
        string="Proveedor manual para POS",
        help=(
            "Indica que este proveedor se utilizará para transacciones "
            "manuales generadas desde el Punto de Venta."
        ),
    )
    has_multiple_pos = fields.Boolean(
        string="Múltiples POS",
        help=(
            "Si está activo, permite restringir explícitamente en qué "
            "configuraciones de POS se podrá utilizar este proveedor manual."
        ),
    )
    multiple_pos_ids = fields.One2many(
        comodel_name="multiple.pos.config",
        inverse_name="payment_provider_id",
        string="POS permitidos",
        help=(
            "Configuración de POS permitidos para este proveedor manual. "
            "Se reutiliza la misma tabla multiple.pos.config del módulo "
            "de múltiples POS."
        ),
    )
    manual_merchant_number = fields.Char(
        string="Número de comercio",
        help=(
            "Número de comercio asociado al proveedor manual utilizado para "
            "identificar la sucursal o tienda en las transacciones."
        ),
    )
    manual_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Diario de pago",
        help=(
            "Diario de pago que se utilizará por defecto al generar "
            "transacciones de pago manuales desde el POS."
        ),
    )
    manual_field_config_ids = fields.One2many(
        comodel_name="manual.payment.field.config",
        inverse_name="provider_id",
        string="Campos a solicitar",
        help=(
            "Define qué campos debe pedir el frontend de POS para la "
            "transacción manual y con qué valor por defecto."
        ),
    )

