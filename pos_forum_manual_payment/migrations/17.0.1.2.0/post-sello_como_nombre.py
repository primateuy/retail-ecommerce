# -*- coding: utf-8 -*-
"""
Reemplaza por su nombre los sellos que quedaron guardados como id del catálogo.

El popup del PDV manda el **id** del registro para los campos relacionales (el
sello es un ``payment.method``). Hasta ahora ese id sólo se resolvía a nombre
cuando el destino configurado era el alias heredado ``stamp``; si el destino era
un campo directo de ``payment.transaction`` —por ejemplo ``issuer_name``,
«Nombre adquirente»— se guardaba el número: en la ficha aparecía «295» en vez de
«Visa Débito».

Acá se corrige lo ya guardado. Sólo se tocan valores que son **un número entero
que corresponde a un registro existente** del modelo configurado: cualquier otra
cosa (un nombre, un texto, un número que no matchea) se deja como está.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    Tx = env["payment.transaction"]
    if "is_pos_manual" not in Tx._fields:
        return

    # Destinos posibles: los que estén configurados con un campo de origen
    # relacional en cualquier proveedor manual.
    destinos = {}
    lineas = env["manual.payment.field.config"].sudo().search([])
    for linea in lineas:
        campo = linea.request_field_id
        if not campo or campo.field_type != "many2one":
            continue
        modelo = campo.relation_model_id.model if campo.relation_model_id else "payment.method"
        destino = linea.transaction_field_mapping
        if destino and destino in Tx._fields:
            destinos.setdefault(destino, modelo)
    # El alias heredado escribe siempre en estos dos.
    destinos.setdefault("acquirer", "payment.method")
    destinos.setdefault("manual_stamp", "payment.method")

    corregidas = 0
    for destino, modelo in destinos.items():
        if modelo not in env:
            continue
        # Sólo las que tienen un número guardado en ese campo.
        cr.execute(
            'SELECT id, "%s" FROM payment_transaction '
            'WHERE is_pos_manual IS TRUE AND "%s" ~ \'^[0-9]+$\'' % (destino, destino)
        )
        filas = cr.fetchall()
        if not filas:
            continue
        cache = {}
        for tx_id, valor in filas:
            registro_id = int(valor)
            if registro_id not in cache:
                registro = env[modelo].sudo().browse(registro_id)
                cache[registro_id] = registro.display_name if registro.exists() else None
            nombre = cache[registro_id]
            if not nombre:
                continue
            Tx.browse(tx_id).sudo().write({destino: nombre})
            corregidas += 1

    _logger.info(
        "pos_forum_manual_payment: sellos corregidos de id a nombre en %s campo(s) "
        "de transacción | %s valores reemplazados.", len(destinos), corregidas,
    )
