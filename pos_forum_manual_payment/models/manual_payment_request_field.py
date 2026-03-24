# -*- coding: utf-8 -*-
"""
Catálogo de campos solicitables para pagos manuales POS.

Este modelo representa la tabla base de "campo a solicitar" que luego se
utiliza en la tabla de configuración del proveedor.
"""

from odoo import fields, models


class ManualPaymentRequestField(models.Model):
    """
    Define cada campo funcional que puede solicitarse en el POS.

    Cada registro describe el tipo de dato y, cuando aplica, el modelo
    relacionado para campos de tipo many2one.
    """

    _name = "manual.payment.request.field"
    _description = "Campo a solicitar en pago manual"
    _order = "sequence, id"

    sequence = fields.Integer(
        string="Secuencia",
        default=10,
        help="Orden de despliegue recomendado para el campo.",
    )
    name = fields.Char(
        string="Nombre",
        required=True,
        help="Nombre funcional del campo que se mostrará al usuario.",
    )
    code = fields.Char(
        string="Código técnico",
        required=True,
        help="Identificador técnico único del campo dentro del catálogo.",
    )
    field_type = fields.Selection(
        selection=[
            ("char", "Texto"),
            ("many2one", "Many2one"),
        ],
        string="Tipo de campo",
        required=True,
        default="char",
        help="Tipo de dato del campo a solicitar en POS.",
    )
    relation_model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Entidad relacionada",
        help=(
            "Entidad relacionada cuando el campo es de tipo many2one. "
            "Ejemplo: para Sello, puede ser payment.method."
        ),
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
        help="Permite archivar campos del catálogo sin eliminarlos.",
    )

