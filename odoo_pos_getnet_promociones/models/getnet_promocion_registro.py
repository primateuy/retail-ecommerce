# -*- coding: utf-8 -*-
"""
Rastro de las promociones Getnet sobre cada pedido.

Dos registros y no uno: la LECTURA es el diálogo técnico con el pinpad (qué se
posteó, qué contestó, con los datos sensibles fuera), y el EVENTO es lo que
pasó con la promoción en la venta (se aplicó, se quitó, no coincidió, el
cajero siguió sin ella). El evento es lo que va a leer quien audite por qué
una venta salió con descuento; la lectura, quien diagnostique el primer cobro
real contra el concentrador.
"""

import json

from odoo import fields, models

EVENTOS = [
    ('aplicada_auto', 'Aplicada por lectura de tarjeta (B)'),
    ('aplicada_manual', 'Elegida por el cajero (A)'),
    ('sin_promo', 'La tarjeta leída no tiene promoción'),
    ('pasa_a_manual', 'La lectura falló: pasa a selección manual'),
    ('pago_dividido', 'Pago dividido: sin promoción'),
    ('quitada', 'Quitada por el cajero'),
    ('no_aplicada', 'PROMO NO APLICADA'),
    ('seguir_sin_promo', 'El cajero siguió sin la promoción'),
    ('no_coincide', 'PROMO NO COINCIDE'),
    ('reversada', 'Cobro reversado (DEV) por la promoción'),
]


class GetnetPromocionEvento(models.Model):
    _name = 'getnet.promocion.evento'
    _description = 'Evento de promoción Getnet en un pedido'
    _order = 'id desc'

    order_id = fields.Many2one(
        'pos_backend.order', string='Pedido', required=True, index=True,
        ondelete='cascade')
    promocion_id = fields.Many2one(
        'getnet.promocion', string='Promoción', ondelete='set null')
    evento = fields.Selection(EVENTOS, string='Evento', required=True)
    detalle = fields.Char(string='Detalle')
    importe_descuento = fields.Float(string='Descuento', digits=(16, 2))
    tarjeta = fields.Char(
        string='Tarjeta', help='Sello, emisor, tipo y BIN. Nunca el número.')
    ticket = fields.Char(string='Ticket Getnet')
    user_id = fields.Many2one(
        'res.users', string='Usuario', default=lambda self: self.env.user,
        ondelete='set null')
    company_id = fields.Many2one(
        related='order_id.company_id', store=True, string='Compañía')


class GetnetLecturaTarjeta(models.Model):
    _name = 'getnet.lectura.tarjeta'
    _description = 'Lectura previa de tarjeta en el pinpad Getnet'
    _order = 'id desc'

    order_id = fields.Many2one(
        'pos_backend.order', string='Pedido', required=True, index=True,
        ondelete='cascade')
    payment_method_id = fields.Many2one(
        'pos_backend.box.payment.method', string='Medio', ondelete='set null')
    terminal_id = fields.Many2one(
        'getnet.pos.terminal', string='Terminal', ondelete='set null')
    token = fields.Char(string='Token', copy=False)
    state = fields.Selection([
        ('esperando', 'Esperando la tarjeta'),
        ('leida', 'Leída'),
        ('fallida', 'Falló'),
    ], string='Estado', default='esperando', required=True)
    motivo = fields.Char(string='Motivo')
    datos = fields.Char(
        string='Datos leídos',
        help='TarjetaId, EmisorId, TarjetaTipo y el BIN. Nunca el número.')
    respuesta = fields.Text(
        string='Respuesta cruda (saneada)',
        help='Lo que devolvió el concentrador, sin número de tarjeta, titular '
             'ni credenciales. Para diagnosticar el primer cobro real.')
    fecha_lectura = fields.Datetime(string='Leída a las')
    company_id = fields.Many2one(
        related='order_id.company_id', store=True, string='Compañía')

    def _tarjeta(self):
        self.ensure_one()
        try:
            return json.loads(self.datos or '{}')
        except ValueError:
            return {}
