# -*- coding: utf-8 -*-
"""La ventana de gracia, que es lo único configurable de este módulo."""

from odoo import fields, models

# Cota por defecto de la ventana de gracia de `terminal_authorize`, en
# segundos. Tiene que quedar CÓMODAMENTE por debajo del timeout del pedido
# HTTP del POS: esta espera no puede ser nunca la causa de un request colgado.
GETNET_VENTANA_DEFAULT = 4


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    getnet_ventana_autorizacion = fields.Integer(
        string='Ventana de espera en el cobro (s)',
        default=GETNET_VENTANA_DEFAULT,
        help='Cuántos segundos espera el POS Backend la respuesta del pinpad '
             'antes de dejar el cobro «sin confirmar» y resolverlo por '
             'consulta. Con la tarjeta ya en la mano la terminal suele '
             'contestar dentro de esta ventana, y el cajero no ve ningún '
             'pendiente. En CERO la ventana se apaga: el cobro queda sin '
             'confirmar siempre y se resuelve con el botón Consultar. '
             'Subirla por encima del timeout del navegador no acelera nada: '
             'cuelga la pantalla.',
    )
