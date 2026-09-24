# -*- coding: utf-8 -*-
"""Deja la moneda del limite FE solo en los contactos que usan la funcionalidad.

Hasta la 17.0.1.3.0 `pos_fe_max_amount_currency_id` tenia
`default=lambda self: self.env.company.currency_id`, con lo cual quedaba cargada
en TODOS los contactos creados por el ORM, usaran o no el control de monto
maximo.

Eso importa por como recomputa Odoo. `pos_fe_max_amount_company_currency`
depende de las cotizaciones, y el motor resuelve a quien recomputar con
`search([(campo, 'in', ids)])`. Antes ese campo era `company_currency_id`
—compute sin store ni search—, el leaf se descartaba y el dominio quedaba vacio:
recomputaba `res.partner` entero ante cualquier cambio de cotizacion. Con
647.000 contactos eso termina en MemoryError, y el cron del BCU escribe
cotizaciones por su cuenta.

La dependencia ahora pasa por `pos_fe_max_amount_currency_id`, que si es stored.
Para que ese search devuelva solo a los que usan la funcionalidad hace falta que
el campo este vacio en el resto, que es lo que hace esta migracion. De aca en
mas el invariante lo sostienen `create`/`write`.

Va por SQL directo: es un UPDATE de una columna sobre cientos de miles de filas y
no hay ningun compute ni constraint que dependa de el mas alla del que estamos
justamente tratando de acotar.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE res_partner
           SET pos_fe_max_amount_currency_id = NULL
         WHERE pos_fe_max_amount_currency_id IS NOT NULL
           AND coalesce(pos_fe_amount_limit_control, false) = false
    """)
    limpiados = cr.rowcount

    cr.execute("""
        SELECT count(*) FROM res_partner
         WHERE coalesce(pos_fe_amount_limit_control, false) = true
    """)
    con_control = cr.fetchone()[0]

    _logger.info(
        "pos_forum_customer_ui: moneda del limite FE limpiada en %s contactos "
        "sin control activo; quedan %s con la funcionalidad en uso, que son los "
        "unicos que se recomputan ante un cambio de cotizacion.",
        limpiados, con_control,
    )
