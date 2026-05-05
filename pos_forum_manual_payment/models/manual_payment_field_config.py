# -*- coding: utf-8 -*-
"""
Configuración de campos manuales para transacciones POS.

Este modelo define los campos que debe solicitar el frontend del POS al usar
un proveedor manual, incluyendo obligatoriedad y valor por defecto.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Tipos de campo de payment.transaction soportados como destino del mapeo.
# La conversión del valor capturado en POS al tipo correspondiente la hace
# _forum_coerce_value_for_field en payment_transaction.py.
SUPPORTED_TX_FIELD_TYPES = (
    "char", "text", "integer", "float", "monetary",
    "boolean", "date", "datetime", "selection", "many2one",
)


class ManualPaymentFieldConfig(models.Model):
    """
    Tabla de configuración de campos para pagos manuales.

    Se utiliza para parametrizar qué datos del pago manual deben pedirse
    en el POS y con qué valor inicial.
    """

    _name = "manual.payment.field.config"
    _description = "Configuración de campos de pago manual"
    _order = "sequence, id"

    sequence = fields.Integer(
        string="Secuencia",
        default=10,
        help="Orden en el que se mostrará el campo en la interfaz del POS.",
    )
    provider_id = fields.Many2one(
        comodel_name="payment.provider",
        string="Proveedor de pago",
        required=True,
        ondelete="cascade",
        help="Proveedor manual al que pertenece esta configuración de campo.",
    )
    request_field_id = fields.Many2one(
        comodel_name="manual.payment.request.field",
        string="Campo a solicitar",
        required=True,
        ondelete="restrict",
        help="Campo funcional del catálogo que debe solicitarse en POS.",
    )
    required = fields.Boolean(
        string="Obligatorio",
        default=True,
        help="Indica si el campo debe completarse obligatoriamente en POS.",
    )
    default_char_value = fields.Char(
        string="Valor por defecto (texto)",
        help="Valor por defecto cuando el campo configurado es de tipo texto.",
    )
    default_reference = fields.Reference(
        string="Valor por defecto (relación)",
        selection="_selection_reference_models",
        help=(
            "Valor por defecto cuando el campo es relacional. Para 'Sello', "
            "se selecciona una marca del método de pago (payment.method)."
        ),
    )

    request_field_type = fields.Selection(
        related="request_field_id.field_type",
        string="Tipo de campo",
        store=False,
        readonly=True,
    )
    transaction_field_mapping = fields.Selection(
        selection="_selection_transaction_fields",
        string="Dato en payment.transaction",
        default="none",
        required=True,
        help=(
            "Define en qué campo de payment.transaction se guarda el valor "
            "capturado en el POS. La lista se genera dinámicamente con los "
            "campos disponibles en el modelo. Si elige «Sin mapeo explícito», "
            "se intenta deducir el destino por sinónimos del código técnico."
        ),
    )

    @api.model
    def _selection_transaction_fields(self):
        """
        Genera dinámicamente las opciones del campo transaction_field_mapping
        a partir de los campos escriturables de payment.transaction cuyo tipo
        es soportado por el coercionador (ver SUPPORTED_TX_FIELD_TYPES).

        Incluye «none» para el mapeo por sinónimos y los alias heredados
        (ticket, batch, etc.) para retrocompatibilidad con registros existentes.
        """
        result = [("none", "Sin mapeo explícito (usa sinónimos por código de campo)")]
        # Alias heredados: permiten que registros existentes sigan funcionando
        _legacy_aliases = {
            "ticket": "Número de ticket (alias heredado)",
            "batch": "Número de lote (alias heredado)",
            "authorization": "Código de autorización (alias heredado)",
            "card_bin": "BIN de la tarjeta (alias heredado)",
            "last_four": "Últimos 4 dígitos (alias heredado)",
            "holder": "Nombre del titular (alias heredado)",
            "stamp": "Sello / marca (alias heredado)",
        }
        for key, label in _legacy_aliases.items():
            result.append((key, label))
        # Campos reales de payment.transaction soportados (no readonly, no
        # computed, no related). Se excluyen los alias heredados para evitar
        # claves duplicadas en el Selection.
        tx_model = self.env["payment.transaction"]
        skip_fields = {
            "id", "display_name", "create_uid", "create_date",
            "write_uid", "write_date", "__last_update",
        } | set(_legacy_aliases)
        for fname, field_obj in sorted(tx_model._fields.items()):
            if fname in skip_fields:
                continue
            if field_obj.type not in SUPPORTED_TX_FIELD_TYPES:
                continue
            if field_obj.readonly or field_obj.compute or field_obj.related:
                continue
            label = field_obj.string or fname
            # Incluir el tipo entre paréntesis para que el usuario sepa qué
            # formato espera el campo destino.
            result.append((fname, "%s (%s) [%s]" % (label, fname, field_obj.type)))
        return result

    @api.model
    def _selection_reference_models(self):
        """
        Retorna entidades habilitadas para valores por defecto relacionales.

        Se define con modelos explícitos para evitar referencias arbitrarias
        y mantener seguridad en la configuración.
        """
        return [
            ("payment.method", "Método de pago / Marca"),
        ]

    @api.onchange("request_field_id")
    def _onchange_request_field_id(self):
        """
        Limpia valores por defecto incompatibles al cambiar el campo solicitado.

        Si el campo pasa a tipo texto se limpia referencia; si pasa a tipo
        relacional se limpia el texto por defecto.
        """
        for rec in self:
            if rec.request_field_id.field_type == "char":
                rec.default_reference = False
            elif rec.request_field_id.field_type == "many2one":
                rec.default_char_value = False

    @api.constrains("request_field_id", "default_reference")
    def _constrain_default_reference_model(self):
        """
        Valida coherencia entre el campo relacional y la entidad por defecto.

        Se exige que el modelo del valor por defecto coincida con el modelo
        relacionado configurado en el catálogo de campos.
        """
        for rec in self:
            if rec.request_field_id.field_type != "many2one" or not rec.default_reference:
                continue
            relation_model = rec.request_field_id.relation_model_id.model if rec.request_field_id.relation_model_id else False
            if relation_model and rec.default_reference._name != relation_model:
                raise ValidationError(
                    "El valor por defecto relacional no coincide con la entidad del campo configurado."
                )


