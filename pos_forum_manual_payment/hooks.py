# -*- coding: utf-8 -*-
"""
Hooks de instalación para el módulo de pagos manuales POS.

Este archivo contiene la lógica de post-instalación para dejar creada una
configuración inicial funcional del proveedor manual, en línea con el
requerimiento funcional del documento.
"""

import logging

_logger = logging.getLogger(__name__)

# Mapeo inicial por código de catálogo → campo «Dato en payment.transaction».
_FORUM_DEFAULT_TX_MAPPING_BY_CATALOG_CODE = {
    "ticket_number": "ticket",
    "batch_number": "batch",
    "authorization_code": "authorization",
    "card_bin": "card_bin",
    "last_four_digits": "last_four",
    "holder_name": "holder",
    "stamp": "stamp",
}


def post_init_hook(env):
    """
    Ejecuta la configuración inicial del módulo al finalizar la instalación.

    Flujo principal:
    1) Garantiza que exista un proveedor manual por compañía.
    2) Asigna un diario por defecto (banco/caja) para la compañía.
    3) Completa número de comercio por defecto si está vacío.
    4) Asocia POS permitidos para que quede utilizable desde el inicio.
    """
    try:
        _logger.info("Iniciando post-instalación de POS pagos manuales FORUM")
        _ensure_manual_provider_defaults(env)
        _logger.info("Post-instalación de POS pagos manuales FORUM finalizada")
    except Exception as error:
        _logger.error(
            "Error en post-instalación de POS pagos manuales FORUM: %s",
            str(error),
        )


def _ensure_manual_provider_defaults(env):
    """
    Crea y completa la configuración por defecto del proveedor manual por compañía.

    La estrategia por compañía evita mezclar configuraciones entre empresas y
    deja al menos un proveedor funcional al instalar el módulo.
    """
    provider_model = env["payment.provider"].sudo()
    journal_model = env["account.journal"].sudo()
    pos_config_model = env["pos.config"].sudo()
    payment_method_model = env["payment.method"].sudo()
    company_model = env["res.company"].sudo()
    multiple_pos_model = env["multiple.pos.config"].sudo()
    manual_field_config_model = env["manual.payment.field.config"].sudo()
    request_field_model = env["manual.payment.request.field"].sudo()

    # Se usa Card por defecto para mantener compatibilidad con transacciones de tarjeta.
    card_method = payment_method_model.search([("code", "=", "card")], limit=1)

    for company in company_model.search([]):
        # Buscar proveedor manual existente para la compañía actual.
        provider = provider_model.search(
            [
                ("company_id", "=", company.id),
                ("code", "=", "forum_manual"),
            ],
            limit=1,
        )

        # Seleccionar diario por defecto priorizando banco/caja.
        default_journal = journal_model.search(
            [
                ("company_id", "=", company.id),
                ("type", "in", ("bank", "cash")),
            ],
            order="id asc",
            limit=1,
        )

        # Obtener POS de la compañía para dejar la configuración utilizable.
        company_pos_records = pos_config_model.search([("company_id", "=", company.id)])

        provider_values = {
            "name": "FORUM Manual POS",
            "code": "forum_manual",
            "state": "enabled",
            "company_id": company.id,
            "manual_pos_provider": True,
            "has_multiple_pos": bool(company_pos_records),
            "manual_merchant_number": "000000",
            "manual_journal_id": default_journal.id if default_journal else False,
        }

        # Incluir método de pago Card solo si existe en el sistema.
        if card_method:
            provider_values["payment_method_ids"] = [(6, 0, [card_method.id])]

        if provider:
            # Actualizar solo los campos funcionales para no sobrescribir datos de negocio.
            provider.write(
                {
                    "manual_pos_provider": True,
                    "has_multiple_pos": bool(company_pos_records),
                    "manual_merchant_number": provider.manual_merchant_number or "000000",
                    "manual_journal_id": provider.manual_journal_id.id or provider_values["manual_journal_id"],
                }
            )
            if card_method and card_method not in provider.payment_method_ids:
                provider.payment_method_ids = [(4, card_method.id)]
            _ensure_multiple_pos_entries(
                multiple_pos_model=multiple_pos_model,
                provider=provider,
                company_pos_records=company_pos_records,
            )
            _ensure_default_field_configuration(
                manual_field_config_model=manual_field_config_model,
                request_field_model=request_field_model,
                provider=provider,
            )
            _logger.info(
                "Proveedor manual existente actualizado para compañía %s",
                company.name,
            )
        else:
            provider = provider_model.create(provider_values)
            _ensure_multiple_pos_entries(
                multiple_pos_model=multiple_pos_model,
                provider=provider,
                company_pos_records=company_pos_records,
            )
            _ensure_default_field_configuration(
                manual_field_config_model=manual_field_config_model,
                request_field_model=request_field_model,
                provider=provider,
            )
            _logger.info(
                "Proveedor manual creado para compañía %s con diario %s",
                company.name,
                default_journal.display_name if default_journal else "N/A",
            )


def _ensure_multiple_pos_entries(multiple_pos_model, provider, company_pos_records):
    """
    Garantiza registros en multiple.pos.config para los POS de la compañía.

    Esta función reutiliza la tabla multiple.pos.config para cumplir el
    requerimiento de configuración de múltiples POS del proveedor manual.
    """
    for pos_config in company_pos_records:
        existing_entry = multiple_pos_model.search(
            [
                ("payment_provider_id", "=", provider.id),
                ("name", "=", pos_config.name),
            ],
            limit=1,
        )
        if not existing_entry:
            multiple_pos_model.create(
                {
                    "name": pos_config.name,
                    "codigo_terminal": str(pos_config.id),
                    "payment_provider_id": provider.id,
                }
            )


def _ensure_default_field_configuration(manual_field_config_model, request_field_model, provider):
    """
    Crea la configuración por defecto de campos para el proveedor manual.

    Incluye los 7 campos requeridos en el documento funcional y deja
    asociado un Many2one por defecto en el proveedor.
    """
    request_fields = _ensure_request_fields_catalog(request_field_model)

    created_or_existing_records = manual_field_config_model.browse()
    sequence = 10
    for request_field in request_fields:
        config = manual_field_config_model.search(
            [
                ("provider_id", "=", provider.id),
                ("request_field_id", "=", request_field.id),
            ],
            limit=1,
        )
        if not config:
            config_values = {
                "provider_id": provider.id,
                "request_field_id": request_field.id,
                "required": True,
                "sequence": sequence,
            }
            if request_field.code == "holder_name":
                # Valor por defecto funcional solicitado: nombre del cliente.
                config_values["default_char_value"] = "partner_name"
            if request_field.code == "stamp":
                default_stamp = _get_default_stamp_for_provider(provider)
                if default_stamp:
                    config_values["default_reference"] = f"payment.method,{default_stamp.id}"
            config_values["transaction_field_mapping"] = (
                _FORUM_DEFAULT_TX_MAPPING_BY_CATALOG_CODE.get(
                    request_field.code, "none"
                )
            )
            config = manual_field_config_model.create(
                config_values
            )
        else:
            # Completar defaults faltantes en configuraciones existentes para
            # asegurar que el proveedor quede funcional tras la instalación.
            update_values = {}
            if not config.required:
                update_values["required"] = True
            if request_field.code == "holder_name" and not config.default_char_value:
                update_values["default_char_value"] = "partner_name"
            if request_field.code == "stamp" and not config.default_reference:
                default_stamp = _get_default_stamp_for_provider(provider)
                if default_stamp:
                    update_values["default_reference"] = f"payment.method,{default_stamp.id}"
            expected_mapping = _FORUM_DEFAULT_TX_MAPPING_BY_CATALOG_CODE.get(
                request_field.code
            )
            if (
                expected_mapping
                and getattr(config, "transaction_field_mapping", "none") == "none"
            ):
                update_values["transaction_field_mapping"] = expected_mapping
            if update_values:
                config.write(update_values)
        created_or_existing_records |= config
        sequence += 10

    # No se define un Many2one "configuración por defecto" en proveedor,
    # ya que el requerimiento funcional utiliza únicamente la tabla one2many.


def _ensure_request_fields_catalog(request_field_model):
    """
    Crea (si no existen) los campos base solicitables del flujo manual.

    Esta tabla es la entidad de "campo a solicitar" referenciada por la
    configuración del proveedor mediante Many2one.
    """
    field_definitions = [
        ("ticket_number", "Número de ticket", "char", False),
        ("batch_number", "Lote", "char", False),
        ("authorization_code", "Código de autorización", "char", False),
        ("card_bin", "BIN de la tarjeta", "char", False),
        ("last_four_digits", "Últimos 4 dígitos", "char", False),
        ("holder_name", "Nombre", "char", False),
        ("stamp", "Sello", "many2one", "payment.method"),
    ]

    created_or_existing = request_field_model.browse()
    sequence = 10
    for code, name, field_type, relation_model in field_definitions:
        request_field = request_field_model.search([("code", "=", code)], limit=1)
        values = {
            "sequence": sequence,
            "name": name,
            "code": code,
            "field_type": field_type,
            "active": True,
        }
        if relation_model:
            model = request_field_model.env["ir.model"].sudo().search(
                [("model", "=", relation_model)],
                limit=1,
            )
            values["relation_model_id"] = model.id if model else False
        if request_field:
            request_field.write(values)
        else:
            request_field = request_field_model.create(values)
        created_or_existing |= request_field
        sequence += 10
    return created_or_existing.sorted("sequence")


def _get_default_stamp_for_provider(provider):
    """
    Obtiene el sello por defecto según método de pago del proveedor.

    Si el proveedor tiene Card asociado, se busca una marca hija de Card y
    se prioriza la que tenga nombre OCA.
    """
    payment_method_model = provider.env["payment.method"].sudo()
    card_method = provider.payment_method_ids.filtered(lambda pm: pm.code == "card")[:1]
    if not card_method:
        card_method = payment_method_model.search([("code", "=", "card")], limit=1)
    if not card_method:
        return False

    # Buscar marcas asociadas al método primario Card.
    card_brands = payment_method_model.search(
        [("primary_payment_method_id", "=", card_method.id)],
        order="name asc",
    )

    # Priorizar OCA y luego VISA explícitamente, como se solicita.
    preferred_names = ["oca", "visa"]
    for preferred_name in preferred_names:
        preferred_brand = card_brands.filtered(
            lambda brand: (brand.name or "").strip().lower() == preferred_name
        )[:1]
        if preferred_brand:
            return preferred_brand

    # Fallback: buscar por nombre global si no existen como marca hija.
    for preferred_name in preferred_names:
        global_preferred = payment_method_model.search(
            [("name", "=ilike", preferred_name)],
            order="id asc",
            limit=1,
        )
        if global_preferred:
            return global_preferred

    # Último fallback: primera marca disponible.
    return card_brands[:1] if card_brands else False

