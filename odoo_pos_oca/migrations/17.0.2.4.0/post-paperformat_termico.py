# -*- coding: utf-8 -*-
"""
Asigna el formato de papel térmico de 80 mm al ticket de cambio y al voucher OCA.

Por qué hace falta una migración y no alcanza con el XML:

``noupdate`` se guarda por REGISTRO en ``ir.model.data``, no por declaración. En
las bases donde estos dos ``ir.actions.report`` quedaron marcados con
``noupdate = true`` (verificado en o17_support_forum el 25-09-2026), el
``<field name="paperformat_id">`` que se agregó al XML **no se aplica**: Odoo
no falla ni avisa, simplemente no escribe nada. Y sin formato propio el reporte
hereda el de la compañía (A4) o el «Ticket» B7 de 88 x 125 mm que había puesto
a mano: en los dos casos el documento se maqueta más ancho que los ~72 mm que
imprime el rollo y sale recortado de los dos lados.

Además se destilda el ``noupdate`` de esos dos registros, que están definidos
enteros en el XML del módulo: así el próximo cambio se aplica solo y no hace
falta otra migración.
"""

import logging

_logger = logging.getLogger(__name__)

_REPORTES = (
    "action_report_pos_order_change_ticket",
    "action_report_payment_transaction_oca_voucher",
)


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        SELECT res_id FROM ir_model_data
         WHERE module = 'odoo_pos_oca'
           AND model = 'report.paperformat'
           AND name = 'paperformat_pos_thermal_80'
        """
    )
    fila = cr.fetchone()
    if not fila:
        _logger.warning(
            "odoo_pos_oca: no se encontró paperformat_pos_thermal_80; "
            "no se reasigna el formato de papel de los reportes térmicos."
        )
        return
    paperformat_id = fila[0]

    cr.execute(
        """
        UPDATE ir_act_report_xml r
           SET paperformat_id = %s
          FROM ir_model_data d
         WHERE d.module = 'odoo_pos_oca'
           AND d.model = 'ir.actions.report'
           AND d.name IN %s
           AND r.id = d.res_id
           AND (r.paperformat_id IS DISTINCT FROM %s)
        """,
        (paperformat_id, _REPORTES, paperformat_id),
    )
    actualizados = cr.rowcount

    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'odoo_pos_oca'
           AND model = 'ir.actions.report'
           AND name IN %s
           AND noupdate
        """,
        (_REPORTES,),
    )
    destildados = cr.rowcount

    _logger.info(
        "odoo_pos_oca: formato térmico 80 mm asignado a %s reporte(s); "
        "noupdate destildado en %s registro(s).",
        actualizados,
        destildados,
    )
