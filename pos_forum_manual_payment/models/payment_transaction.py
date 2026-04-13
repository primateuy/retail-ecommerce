# -*- coding: utf-8 -*-
"""
Extensión de payment.transaction para pagos manuales en POS.

Este modelo agrega campos específicos para almacenar la información propia
de las transacciones manuales realizadas desde el Punto de Venta, tales como:
- Número de ticket.
- Lote.
- Código de autorización.
- BIN y últimos dígitos de la tarjeta.
- Nombre del titular y sello utilizado.
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Destino lógico → (campo OCA en payment.transaction o False, campo manual_* o False).
FORUM_TX_FIELD_TARGETS = {
    "ticket": ("ticket_number", "manual_ticket_number"),
    "batch": ("batch_number", "manual_batch_number"),
    "authorization": ("authorization_code", "manual_auth_code"),
    "card_bin": ("card_bin", "manual_card_bin"),
    "last_four": ("card_last_four", "manual_last_four"),
    "holder": (False, "manual_holder_name"),
    "stamp": ("acquirer", "manual_stamp"),
}

# Si transaction_field_mapping = none: inferir destino por código del catálogo (cualquier idioma/código usado en BD).
FORUM_REQUEST_CODE_TO_TARGET = {
    "ticket_number": "ticket",
    "nro_ticket": "ticket",
    "batch_number": "batch",
    "lote": "batch",
    "authorization_code": "authorization",
    "cod_auto": "authorization",
    "card_bin": "card_bin",
    "bin_tarjeta": "card_bin",
    "last_four_digits": "last_four",
    "ultimos_digitos": "last_four",
    "holder_name": "holder",
    "nombre": "holder",
    "titular": "holder",
    "stamp": "stamp",
    "sello": "stamp",
}


class PaymentTransaction(models.Model):
    """
    Extensión del modelo payment.transaction para pagos manuales POS.

    Permite identificar qué transacciones provienen del flujo manual del POS
    y almacenar la información adicional capturada en el popup del Punto de
    Venta, asegurando trazabilidad completa de la operación.
    """

    _inherit = "payment.transaction"

    is_pos_manual = fields.Boolean(
        string="Transacción POS manual",
        help=(
            "Indica que esta transacción fue generada desde el flujo manual "
            "del Punto de Venta."
        ),
    )
    manual_ticket_number = fields.Char(
        string="Número de ticket",
        help="Número de ticket asociado a la transacción manual.",
    )
    manual_batch_number = fields.Char(
        string="Número de lote",
        help="Número de lote asociado a la transacción manual.",
    )
    manual_auth_code = fields.Char(
        string="Código de autorización",
        help="Código de autorización asociado a la transacción manual.",
    )
    manual_card_bin = fields.Char(
        string="BIN de la tarjeta",
        help="BIN de la tarjeta utilizada en la transacción manual.",
    )
    manual_last_four = fields.Char(
        string="Últimos 4 dígitos",
        help="Últimos 4 dígitos de la tarjeta utilizada en la transacción.",
    )
    manual_holder_name = fields.Char(
        string="Nombre del titular",
        help="Nombre del titular de la tarjeta en la transacción manual.",
    )
    manual_stamp = fields.Char(
        string="Sello",
        help=(
            "Identificador del sello utilizado en la transacción manual. "
            "En una iteración posterior se puede convertir a Many2one."
        ),
    )

    @api.model
    def forum_create_manual_transaction_from_pos_payment(self, pos_payment):
        """
        Crea una transacción de pago manual asociada a un pos.payment.

        Replica el enfoque de create_oca_transaction (odoo_pos_oca): toma montos,
        moneda, partner y vínculos POS del pago/pedido, y los datos de ticket,
        lote, autorización, etc. del JSON capturado en el popup. Marca
        is_pos_manual y enlaza pos_payment_id para que _create_payment de OCA
        no genere account.payment duplicado.

        :param pos.payment pos_payment: Pago POS ya persistido.
        :return: payment.transaction creado o vacío si no aplica / ya existe.
        """
        if not pos_payment:
            _logger.debug("FORUM manual POS: sin pos.payment; no se crea transacción.")
            return self.env["payment.transaction"]
        pos_payment.ensure_one()
        # No crear transacción para vueltos / líneas de cambio.
        if pos_payment.is_change:
            _logger.info(
                "FORUM manual POS: pago %s omitido (línea de vuelto/cambio).",
                pos_payment.id,
            )
            return self.env["payment.transaction"]
        # Idempotencia: no duplicar si el pago ya tiene transacción vinculada.
        if pos_payment.payment_transaction_id:
            _logger.info(
                "FORUM manual POS: pago %s ya vinculado a transacción %s (idempotente).",
                pos_payment.id,
                pos_payment.payment_transaction_id.id,
            )
            return pos_payment.payment_transaction_id
        pos_method = pos_payment.payment_method_id
        if not pos_method.manual_transaction_enabled or not pos_method.manual_provider_id:
            _logger.debug(
                "FORUM manual POS: pago %s método «%s» sin transacción manual; omitido.",
                pos_payment.id,
                pos_method.display_name,
            )
            return self.env["payment.transaction"]
        if not pos_payment.manual_payment_values_json:
            _logger.warning(
                "FORUM manual POS: pago %s sin manual_payment_values_json (validación debería "
                "haberlo impedido en POS).",
                pos_payment.id,
            )
            raise ValidationError(
                _(
                    "El pago POS %(pay)s debe incluir los datos de transacción manual "
                    "(popup). No se puede registrar sin ese JSON."
                )
                % {"pay": pos_payment.id}
            )
        provider = pos_method.manual_provider_id
        order = pos_payment.pos_order_id
        if not order:
            _logger.warning(
                "FORUM manual POS: pago %s sin pos_order_id.",
                pos_payment.id,
            )
            raise ValidationError(
                _(
                    "El pago POS %(pay)s no está vinculado a un pedido; no se puede "
                    "crear la transacción manual."
                )
                % {"pay": pos_payment.id}
            )
        payment_method_tx = self._forum_resolve_provider_payment_method(provider)
        if not payment_method_tx:
            _logger.warning(
                "FORUM manual POS: proveedor manual id=%s sin payment.method asociado.",
                provider.id,
            )
            raise ValidationError(
                _(
                    "El proveedor manual «%(prov)s» no tiene ningún método de pago "
                    "(payment.method) configurado; asocie al menos el método «card»."
                )
                % {"prov": provider.display_name}
            )
        partner = order.partner_id or order.company_id.partner_id
        manual_vals = self._forum_parse_manual_payment_json(
            pos_payment.manual_payment_values_json
        )
        mapped_fields = self._forum_transaction_vals_from_mapped_popup(
            provider, manual_vals
        )
        reference = self._forum_generate_manual_reference(order, pos_payment)
        # Resumen sin datos sensibles del titular/tarjeta (solo trazabilidad).
        _logger.info(
            "FORUM manual POS: creando payment.transaction ref=%s pedido=%s pago=%s "
            "monto=%s moneda=%s proveedor=%s payment.method(tx)=%s campos_popup=%s",
            reference,
            order.name,
            pos_payment.id,
            pos_payment.amount,
            order.currency_id.name,
            provider.display_name,
            payment_method_tx.display_name,
            sorted(manual_vals.keys()),
        )
        vals = {
            "provider_id": provider.id,
            "payment_method_id": payment_method_tx.id,
            "reference": reference,
            "amount": pos_payment.amount,
            "currency_id": order.currency_id.id,
            "state": "done",
            "state_message": _("Transacción manual registrada desde el Punto de Venta."),
            "partner_id": partner.id,
            "operation": "offline",
            "is_post_processed": True,
            "is_pos_manual": True,
            "pos_order_id": order.id,
            "pos_payment_id": pos_payment.id,
            "transaction_origin": "pos_payment",
            "merchant_number": provider.manual_merchant_number or "",
            "invoice_number": order.name or "",
        }
        vals.update(mapped_fields)
        transaction = self.sudo().create(vals)
        # Misma asociación que create_oca_transaction en odoo_pos_oca.
        pos_payment.sudo().payment_transaction_id = transaction.id
        _logger.info(
            "FORUM manual POS: transacción creada id=%s ref=%s is_pos_manual=True "
            "vinculada a pago=%s pedido=%s.",
            transaction.id,
            transaction.reference,
            pos_payment.id,
            order.name,
        )
        return transaction

    @api.model
    def _forum_transaction_target_for_config_line(self, config_line):
        """
        Resuelve el destino lógico para una línea de configuración.

        Prioriza el campo explícito «Dato en payment.transaction»; si es «none»,
        usa sinónimos según el código técnico del campo a solicitar.
        Soporta tanto alias heredados (ticket, batch, …) como nombres de campo
        directos de payment.transaction (manual_ticket_number, etc.).
        """
        selected = config_line.transaction_field_mapping
        if selected and selected != "none":
            return selected
        code = (config_line.request_field_id.code or "").strip().lower()
        return FORUM_REQUEST_CODE_TO_TARGET.get(code)

    @api.model
    def _forum_transaction_vals_from_mapped_popup(self, provider, manual_vals):
        """
        Arma los valores de payment.transaction desde los datos del popup POS.

        Recorre las líneas de configuración del proveedor, toma el valor del JSON
        del POS usando el código del campo a solicitar y lo escribe en los
        destinos definidos. Soporta:
        - Alias heredados (ticket, batch, etc.) via FORUM_TX_FIELD_TARGETS
        - Nombres de campo directos de payment.transaction (cualquier Char/Text)
        """
        base = {}
        # Inicializar campos conocidos del diccionario heredado con cadena vacía
        for _alias, (oca_f, manual_f) in FORUM_TX_FIELD_TARGETS.items():
            if oca_f:
                base[oca_f] = ""
            if manual_f:
                base[manual_f] = ""

        tx_fields = self._fields

        for line in provider.manual_field_config_ids.sorted("sequence"):
            request_field = line.request_field_id
            if not request_field or not request_field.code:
                continue
            code = request_field.code
            target = self._forum_transaction_target_for_config_line(line)
            if not target:
                _logger.debug(
                    "FORUM manual POS: config línea id=%s código JSON «%s» sin destino; "
                    "defina «Dato en payment.transaction» en el proveedor manual.",
                    line.id,
                    code,
                )
                continue

            raw = manual_vals.get(code)

            # Resolver valor según tipo de campo
            if request_field.field_type == "many2one" and target == "stamp":
                value = self._forum_resolve_stamp_label(raw)
            else:
                if raw is None or raw is False:
                    value = ""
                else:
                    value = str(raw).strip()

            if target in FORUM_TX_FIELD_TARGETS:
                # Alias heredado: escribir en ambos campos (OCA + manual_*)
                oca_f, manual_f = FORUM_TX_FIELD_TARGETS[target]
                if oca_f:
                    base[oca_f] = value
                if manual_f:
                    base[manual_f] = value
            elif target in tx_fields:
                # Campo directo de payment.transaction
                base[target] = value
            else:
                _logger.warning(
                    "FORUM manual POS: config línea id=%s mapeo «%s» no es un campo "
                    "válido de payment.transaction; se omite.",
                    line.id,
                    target,
                )
        return base

    @api.model
    def _forum_parse_manual_payment_json(self, json_text):
        """
        Convierte el Text JSON del pos.payment en un diccionario seguro.

        Las claves del diccionario coinciden con manual.payment.request.field.code
        (pueden ser nro_ticket, lote, etc., según el catálogo).
        """
        if not json_text:
            return {}
        try:
            data = json.loads(json_text)
        except (ValueError, TypeError) as error:
            _logger.warning(
                "FORUM manual POS: JSON inválido al parsear manual_payment_values: %s",
                error,
            )
            return {}
        if not isinstance(data, dict):
            _logger.warning(
                "FORUM manual POS: manual_payment_values JSON no es un objeto (tipo=%s).",
                type(data).__name__,
            )
            return {}
        return data

    @api.model
    def _forum_resolve_stamp_label(self, stamp_value):
        """
        Obtiene la etiqueta legible del sello (marca) a partir del id o nombre.

        En el popup, stamp es el id de payment.method (marca hija de Card).
        """
        if stamp_value in (None, False, ""):
            return ""
        payment_method_model = self.env["payment.method"].sudo()
        if isinstance(stamp_value, int):
            brand = payment_method_model.browse(stamp_value)
            return brand.name if brand.exists() else ""
        try:
            stamp_id = int(stamp_value)
        except (ValueError, TypeError):
            return str(stamp_value)
        brand = payment_method_model.browse(stamp_id)
        return brand.name if brand.exists() else ""

    @api.model
    def _forum_resolve_provider_payment_method(self, provider):
        """
        Elige el payment.method (modelo payment) enlazado al proveedor manual.

        Prioriza el método con código 'card', coherente con el hook de instalación.
        """
        methods = provider.payment_method_ids
        card = methods.filtered(lambda m: m.code == "card")[:1]
        return card or (methods[:1] if methods else self.env["payment.method"])

    @api.model
    def _forum_generate_manual_reference(self, pos_order, pos_payment):
        """
        Genera una referencia única estable para la transacción (constraint reference_uniq).
        """
        order_part = (pos_order.name or str(pos_order.id)).replace(" ", "")[:40]
        return "POS-MAN-%s-%s" % (order_part, pos_payment.id)

