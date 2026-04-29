# -*- coding: utf-8 -*-
"""
Pre-migration 17.0.2.0.6 odoo_pos_fiserv_backend.

Limpia ir.model.data e ir.ui.view del meta-módulo viejo ``odoo_pos_fiserv``
que comparten name + priority con la vista del backend. Sin esta limpieza,
ambas vistas se aplican y el arch viejo (con `invisible` menos restrictivo
para el botón Confirmar) sobrescribe el del backend.

Equivalente al pre_init_hook del backend, pero corre en update — donde
pre_init_hook ya no se dispara.
"""

import logging

_logger = logging.getLogger(__name__)

_IRMD_NAMES_MIGRATED_TO_BACKEND = (
    'account_payment_form_fiserv_terminal',
    'view_account_payment_register_form_fiserv',
)


def migrate(cr, version):
    if not version:
        return
    for name in _IRMD_NAMES_MIGRATED_TO_BACKEND:
        try:
            cr.execute(
                "SELECT id, res_id FROM ir_model_data "
                "WHERE module = 'odoo_pos_fiserv_backend' AND name = %s",
                (name,),
            )
            backend_md = cr.fetchone()
            cr.execute(
                "SELECT id, res_id FROM ir_model_data "
                "WHERE module = 'odoo_pos_fiserv' AND name = %s",
                (name,),
            )
            old_md = cr.fetchone()

            if old_md and not backend_md:
                cr.execute(
                    "UPDATE ir_model_data SET module = 'odoo_pos_fiserv_backend' "
                    "WHERE id = %s",
                    (old_md[0],),
                )
                _logger.info(
                    "Fiserv backend pre-migration: %s reasignado de odoo_pos_fiserv → backend",
                    name,
                )
            elif old_md and backend_md:
                old_md_id, old_res_id = old_md
                backend_res_id = backend_md[1]
                cr.execute("DELETE FROM ir_model_data WHERE id = %s", (old_md_id,))
                if old_res_id and old_res_id != backend_res_id:
                    cr.execute("DELETE FROM ir_ui_view WHERE id = %s", (old_res_id,))
                    _logger.info(
                        "Fiserv backend pre-migration: borrado duplicado viejo %s "
                        "(md_id=%s, view_id=%s); backend conserva view_id=%s",
                        name, old_md_id, old_res_id, backend_res_id,
                    )
                else:
                    _logger.info(
                        "Fiserv backend pre-migration: borrado md viejo %s "
                        "(md_id=%s); compartían misma ir.ui.view (id=%s)",
                        name, old_md_id, old_res_id,
                    )
        except Exception as exc:
            _logger.error(
                "Fiserv backend pre-migration: error procesando %s: %s",
                name, exc, exc_info=True,
            )
