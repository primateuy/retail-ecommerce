# -*- coding: utf-8 -*-
"""
Catálogo de promociones por tarjeta para el cobro Getnet del POS Backend.

Un solo catálogo para los dos modos: la misma búsqueda elige sola en la
detección automática y lista las opciones en la selección manual. No es
loyalty: los programas estándar no tienen reglas por tarjeta y el POS Backend
no tiene motor de loyalty (mismo criterio que odoo_pos_oca_promociones).
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Tabla TarjetaId del manual TransAct v4 (General v1.3). La de emisores «es
# cambiante» según el propio manual: confirmar con New Age Data.
TARJETAS = [
    ('1', 'MASTERCARD'), ('2', 'VISA'), ('3', 'DISCOVER'),
    ('4', 'AMERICAN EXPRESS'), ('5', 'TARJETA D'), ('6', 'OCA MASTER'),
    ('8', 'CABAL'), ('9', 'ANDA'), ('12', 'CREDITEL'), ('14', 'PASSCARD'),
    ('15', 'LIDER'), ('16', 'CLUB DEL ESTE'), ('17', 'MAESTRO'),
    ('19', 'EDENRED (Alim.)'), ('20', 'SODEXO (Alim.)'),
    ('21', 'MI DINERO (Alim.)'), ('22', 'MIDES'), ('27', 'DUCSA'),
    ('32', 'OCA PRODUCTO'), ('33', 'AXION'),
]
EMISORES = [
    ('1', 'BROU'), ('2', 'CABAL'), ('3', 'LIDER'), ('4', 'EDENRED'),
    ('5', 'SODEXO'), ('6', 'MIDES'), ('7', 'BANDES'), ('8', 'SCOTIABANK'),
    ('9', 'CITIBANK'), ('10', 'BBVA'), ('11', 'HSBC'), ('12', 'ITAU'),
    ('13', 'SANTANDER'), ('14', 'OCA'), ('15', 'FUCAC'),
    ('16', 'CREDITOS DIRECTOS'), ('17', 'CREDITEL'), ('18', 'ANDA'),
    ('19', 'DISCOVER'), ('20', 'CLUB DEL ESTE'), ('21', 'PASSCARD'),
    ('22', 'PRONTO'), ('23', 'MI DINERO'), ('24', 'ABITAB'), ('25', 'PREX'),
    ('26', 'MASTERCARD'), ('27', 'HERITAGE'), ('1201', 'ITAU INFINITE'),
    ('1302', 'SANTANDER SELECT'),
]
TIPOS = [('CRE', 'Crédito'), ('DEB', 'Débito')]


def _normalizar(valor):
    """'2', 2, '2.0' -> '2'; vacío -> ''."""
    if valor in (None, False, ''):
        return ''
    texto = str(valor).strip()
    try:
        return str(int(float(texto)))
    except ValueError:
        return texto.upper()


class GetnetPromocion(models.Model):
    _name = 'getnet.promocion'
    _description = 'Promoción por tarjeta (Getnet, POS Backend)'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True,
                       help='Lo que ve el cajero: «Getnet · <nombre>».')
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        default=10,
        help='Si una tarjeta califica para varias, gana la de menor secuencia.')
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, ondelete='cascade',
        default=lambda self: self.env.company, index=True)
    date_from = fields.Date(string='Desde')
    date_to = fields.Date(string='Hasta')
    tarjeta_id = fields.Selection(
        TARJETAS, string='Sello',
        help='TarjetaId de TransAct. Vacío: cualquier sello.')
    emisor_id = fields.Selection(
        EMISORES, string='Emisor',
        help='EmisorId de TransAct (el banco). Vacío: cualquier emisor. '
             'La tabla la mantiene New Age Data y cambia.')
    tarjeta_tipo = fields.Selection(
        TIPOS, string='Tipo', help='Vacío: crédito y débito.')
    bines = fields.Char(
        string='BIN',
        help='Opcional. Prefijos de BIN separados por coma (421301, 4546) o '
             'rangos (421300-421399). Vacío: cualquier BIN. El BIN se '
             'verifica al aprobar; el pinpad no lo puede restringir.')
    porcentaje = fields.Float(string='Descuento %', required=True, digits=(5, 2))
    financia = fields.Selection(
        [('campera', 'La empresa'), ('banco', 'El banco / la tarjeta')],
        string='Quién financia', required=True, default='campera',
        help='Sólo cambia la cuenta contable del descuento. La promoción se '
             'registra SIEMPRE como una línea de descuento aparte: los precios '
             'de los productos no se tocan.')
    producto_descuento_id = fields.Many2one(
        'product.product', string='Producto de descuento', required=True,
        ondelete='restrict',
        default=lambda self: self.env.ref(
            'odoo_pos_getnet_promociones.producto_descuento_promocion',
            raise_if_not_found=False),
        help='El producto de la línea de descuento (tipo servicio). La línea '
             'lleva el nombre de la promoción.')
    cuenta_id = fields.Many2one(
        'account.account', string='Cuenta contable', required=True,
        ondelete='restrict', check_company=True,
        help='Donde va el descuento en la factura. Si financia la empresa: la '
             'cuenta de descuentos concedidos. Si financia el banco: la cuenta '
             'del reintegro a reclamarle.')

    @api.constrains('porcentaje')
    def _check_porcentaje(self):
        for promo in self:
            if not 0 < promo.porcentaje < 100:
                raise ValidationError(_('El descuento tiene que estar entre 0 y 100 %.'))

    @api.constrains('cuenta_id', 'producto_descuento_id')
    def _check_cuenta(self):
        # Además del required: la columna no puede ser NOT NULL mientras haya
        # promociones cargadas antes de este campo.
        for promo in self:
            if not promo.cuenta_id or not promo.producto_descuento_id:
                raise ValidationError(_(
                    'La promoción «%s» necesita la cuenta contable del descuento '
                    'y el producto de descuento.', promo.name))

    @api.constrains('bines')
    def _check_bines(self):
        for promo in self:
            promo._rangos_bin()

    @api.constrains('date_from', 'date_to')
    def _check_fechas(self):
        for promo in self:
            if promo.date_from and promo.date_to and promo.date_to < promo.date_from:
                raise ValidationError(_('La fecha «Hasta» es anterior a «Desde».'))

    # ------------------------------------------------------------------
    def _rangos_bin(self):
        """[(desde, hasta)] como strings de 6 a 8 dígitos, o [] = cualquiera."""
        self.ensure_one()
        rangos = []
        for parte in (self.bines or '').split(','):
            parte = parte.strip()
            if not parte:
                continue
            m = re.fullmatch(r'(\d{4,8})(?:\s*-\s*(\d{4,8}))?', parte)
            if not m:
                raise ValidationError(_(
                    'BIN inválido en «%(promo)s»: «%(parte)s». Usá prefijos de 4 '
                    'a 8 dígitos o rangos 421300-421399.',
                    promo=self.name, parte=parte))
            rangos.append((m.group(1), m.group(2) or m.group(1)))
        return rangos

    def _bin_califica(self, iin):
        self.ensure_one()
        rangos = self._rangos_bin()
        if not rangos:
            return True
        iin = re.sub(r'\D', '', str(iin or ''))
        if not iin:
            return False
        for desde, hasta in rangos:
            largo = len(desde)
            if desde <= iin[:largo].ljust(largo, '0') <= hasta.ljust(largo, '9')[:largo]:
                return True
        return False

    def _califica(self, tarjeta):
        """¿La tarjeta leída/aprobada califica para esta promoción?

        ``tarjeta``: dict con tarjeta_id, emisor_id, tarjeta_tipo e iin (lo que
        falte vale '' y sólo califica si la promoción no lo pide).
        """
        self.ensure_one()
        if self.tarjeta_id and _normalizar(tarjeta.get('tarjeta_id')) != self.tarjeta_id:
            return False
        if self.emisor_id and _normalizar(tarjeta.get('emisor_id')) != self.emisor_id:
            return False
        if self.tarjeta_tipo and _normalizar(tarjeta.get('tarjeta_tipo')) != self.tarjeta_tipo:
            return False
        return self._bin_califica(tarjeta.get('iin'))

    @api.model
    def _vigentes(self, company, fecha=None):
        fecha = fecha or fields.Date.context_today(self)
        return self.sudo().search([
            ('company_id', '=', company.id),
            '|', ('date_from', '=', False), ('date_from', '<=', fecha),
            '|', ('date_to', '=', False), ('date_to', '>=', fecha),
        ])

    @api.model
    def _buscar(self, tarjeta, company, fecha=None):
        """La promoción que aplica a esa tarjeta (la de menor secuencia), o vacío."""
        for promo in self._vigentes(company, fecha):
            if promo._califica(tarjeta):
                return promo
        return self.browse()

    def _restriccion(self):
        """Lo que se manda al pinpad para que sólo acepte esa tarjeta (modo A)."""
        self.ensure_one()
        vals = {}
        if self.tarjeta_id:
            vals['TarjetaId'] = int(self.tarjeta_id)
        if self.emisor_id:
            vals['EmisorId'] = int(self.emisor_id)
        if self.tarjeta_tipo:
            vals['TarjetaTipo'] = self.tarjeta_tipo
        return vals

    def _describir(self):
        self.ensure_one()
        partes = [dict(TARJETAS).get(self.tarjeta_id) or '',
                  dict(EMISORES).get(self.emisor_id) or '',
                  dict(TIPOS).get(self.tarjeta_tipo) or '',
                  ('BIN %s' % self.bines) if self.bines else '']
        return '%s %% · %s' % (
            ('%g' % self.porcentaje).replace('.', ','),
            ' '.join(p for p in partes if p) or _('cualquier tarjeta'))
