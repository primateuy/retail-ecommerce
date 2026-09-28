# -*- coding: utf-8 -*-
"""
La promoción Getnet aplicada a un pedido del POS Backend.

Una promoción por pedido, y se aplica y se quita siempre por acá: los dos
modos (lectura de tarjeta y selección manual) terminan en
`_getnet_aplicar_promocion`, y todas las salidas de los avisos en
`_getnet_quitar_promocion`. Nunca se aplica ni se quita sola después de un
cobro aprobado: eso lo decide el cajero con los avisos.

LA PROMOCIÓN ES SIEMPRE UNA LÍNEA DE DESCUENTO APARTE (decisión de Daryl,
27/09/2026), en todos los modos y la financie quien la financie: las líneas de
producto nunca cambian su precio ni su descuento por una promoción, así el
histórico se lee solo. Una línea negativa por cada combinación de impuestos,
con el producto de descuento y el nombre de la promoción, que viaja al
sale.order y a la factura trazable a la promoción y al cobro Getnet. Quién
financia sólo decide la cuenta contable de esa línea (la de la promoción).

Una línea NEGATIVA sale en el CFE de Uruware como ítem con cantidad −1 y
precio positivo: la misma forma que ya firmó Uruware en producción (eTickets
101-A-280511 y siguientes, julio 2026, «15% en tu orden»).
"""

import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosBackendOrder(models.Model):
    _inherit = 'pos_backend.order'

    getnet_promocion_id = fields.Many2one(
        'getnet.promocion', string='Promoción Getnet', readonly=True,
        copy=False, ondelete='restrict')
    getnet_promocion_modo = fields.Selection(
        [('auto', 'Lectura de tarjeta'), ('manual', 'Elegida por el cajero')],
        string='Cómo se aplicó', readonly=True, copy=False)
    getnet_promocion_tarjeta = fields.Char(
        string='Tarjeta de la promoción', readonly=True, copy=False,
        help='Lo leído en el pinpad (sello, emisor, tipo, BIN). Es la '
             'restricción con la que se postea el cobro.')
    getnet_promocion_manual = fields.Boolean(
        string='Promociones en manual', readonly=True, copy=False,
        help='La lectura de tarjeta falló en esta venta: se ofrece la '
             'selección manual y no se vuelve a leer.')
    getnet_promocion_ticket_ok = fields.Char(
        string='Ticket aceptado sin promoción', readonly=True, copy=False,
        help='El cajero vio PROMO NO APLICADA sobre este cobro y siguió sin '
             'la promoción.')
    getnet_promocion_evento_ids = fields.One2many(
        'getnet.promocion.evento', 'order_id', string='Promociones Getnet',
        readonly=True)
    getnet_lectura_ids = fields.One2many(
        'getnet.lectura.tarjeta', 'order_id', string='Lecturas de tarjeta',
        readonly=True, groups='pos_backend.group_pos_supervisor')

    # ------------------------------------------------------------------
    def _getnet_registrar(self, evento, promocion=None, detalle='',
                          importe=0.0, tarjeta=None, ticket=''):
        self.ensure_one()
        return self.env['getnet.promocion.evento'].sudo().create({
            'order_id': self.id,
            'promocion_id': (promocion or self.getnet_promocion_id).id or False,
            'evento': evento,
            'detalle': detalle,
            'importe_descuento': importe,
            'tarjeta': self._getnet_describir_tarjeta(tarjeta) if tarjeta else '',
            'ticket': ticket or '',
        })

    def _getnet_describir_tarjeta(self, tarjeta):
        from .getnet_promocion import EMISORES, TARJETAS, _normalizar
        sello = _normalizar(tarjeta.get('tarjeta_id'))
        emisor = _normalizar(tarjeta.get('emisor_id'))
        return ' · '.join(p for p in (
            dict(TARJETAS).get(sello) or (sello and 'sello %s' % sello) or '',
            dict(EMISORES).get(emisor) or (emisor and 'emisor %s' % emisor) or '',
            tarjeta.get('tarjeta_tipo') or '',
            tarjeta.get('iin') and 'BIN %s' % tarjeta['iin'] or '',
        ) if p)

    def _getnet_cobros_vivos(self):
        """Líneas de pago que cuentan: todo lo que no se descartó ni reversó."""
        self.ensure_one()
        return self.payment_line_ids.filtered(
            lambda linea: linea.state != 'cancelado'
            and linea.integration_state not in ('descartado', 'reversado', 'devuelto')
            and not linea.is_change)

    def _getnet_motivo_pago_dividido(self, importe=None):
        """Por qué la promoción no puede aplicarse a este cobro, o ''.

        La promoción exige que la tarjeta pague el TOTAL: si ya hay otro cobro
        en el pedido, o el cajero va a cobrar con la tarjeta sólo una parte, no
        hay promoción.
        """
        self.ensure_one()
        if self._getnet_cobros_vivos():
            return _('Pago dividido: la promoción sólo aplica si la tarjeta '
                     'paga el total, y el pedido ya tiene otro cobro.')
        moneda = self.currency_id or self.company_id.currency_id
        if importe is not None and moneda.compare_amounts(importe, self.amount_pending) < 0:
            return _('Pago dividido: la promoción sólo aplica si la tarjeta '
                     'paga el total (%(total)s), no una parte (%(parte)s).',
                     total='%.2f' % self.amount_pending, parte='%.2f' % importe)
        return ''

    # ------------------------------------------------------------------
    def _getnet_aplicar_promocion(self, promocion, modo, tarjeta=None):
        """Aplica ``promocion`` al pedido. Devuelve el descuento en plata."""
        self.ensure_one()
        promocion.ensure_one()
        if self.getnet_promocion_id:
            if self.getnet_promocion_id == promocion:
                return 0.0
            self._getnet_quitar_promocion(registrar=False)
        # Mismo control que el descuento global: con cobros confirmados o un
        # cobro de terminal en curso lo que se cobra ya no se toca.
        self._check_lines_editable()
        if not self._get_discountable_lines():
            raise UserError(_('El pedido no tiene productos a los que aplicar '
                              'la promoción.'))
        antes = self.amount_total
        self.sudo().write({
            'getnet_promocion_id': promocion.id,
            'getnet_promocion_modo': modo,
            'getnet_promocion_tarjeta': json.dumps(tarjeta) if tarjeta else False,
        })
        self._getnet_rehacer_lineas_promocion()
        descuento = antes - self.amount_total
        self._getnet_registrar(
            'aplicada_auto' if modo == 'auto' else 'aplicada_manual',
            promocion, detalle=promocion._describir(), importe=descuento,
            tarjeta=tarjeta)
        return descuento

    def _getnet_rehacer_lineas_promocion(self):
        """Borra y vuelve a armar las líneas de descuento de la promoción.

        Se llama al aplicarla y cada vez que cambian los productos del pedido:
        el descuento es un porcentaje de lo que se vende, así que una línea
        armada sobre otro ticket cobraría mal.
        """
        self.ensure_one()
        Line = self.env['pos_backend.order.line'].sudo().with_context(
            pos_backend_authorized=True, getnet_promo_interno=True)
        Line.browse(self.line_ids.filtered('getnet_promocion_id').ids).unlink()
        promocion = self.getnet_promocion_id
        if not promocion:
            return
        grupos = {}
        for linea in self._get_discountable_lines():
            clave = tuple(sorted(linea.tax_ids.ids))
            neto = linea.price_unit * linea.quantity * (1 - linea.discount / 100)
            grupos[clave] = grupos.get(clave, 0.0) + neto
        moneda = self.currency_id or self.company_id.currency_id
        vals = []
        for clave, base in grupos.items():
            importe = moneda.round(base * promocion.porcentaje / 100)
            if not importe:
                continue
            vals.append({
                'order_id': self.id,
                'product_id': promocion.producto_descuento_id.id,
                'description': _('Promoción %s', promocion.name),
                'quantity': 1.0,
                'price_unit': -importe,
                'tax_ids': [(6, 0, list(clave))],
                'is_reward_line': True,
                'getnet_promocion_id': promocion.id,
            })
        Line.create(vals)
        self.invalidate_recordset(['amount_total', 'amount_pending'])

    def _getnet_quitar_promocion(self, registrar=True, motivo=''):
        """Saca la promoción: borra SUS líneas y nada más."""
        self.ensure_one()
        promocion = self.getnet_promocion_id
        if not promocion:
            return
        self._check_lines_editable()
        self.sudo().write({
            'getnet_promocion_id': False,
            'getnet_promocion_modo': False,
            'getnet_promocion_tarjeta': False,
        })
        self._getnet_rehacer_lineas_promocion()
        if registrar:
            self._getnet_registrar('quitada', promocion, detalle=motivo)

    def _getnet_ticket_de_promocion(self):
        """El ticket Getnet del cobro que pagó la promoción, o ''."""
        self.ensure_one()
        cobros = self.payment_line_ids.filtered(
            lambda l: l.integration_state == 'autorizado' and l.state != 'cancelado'
            and l.payment_method_id.terminal_provider == 'getnet')
        return cobros[:1].transaction_id or ''

    def _prepare_sale_order_line_vals(self, line):
        vals = super()._prepare_sale_order_line_vals(line)
        if line.getnet_promocion_id:
            vals['getnet_promocion_id'] = line.getnet_promocion_id.id
            vals['getnet_ticket'] = self._getnet_ticket_de_promocion()
        return vals

    # ------------------------------------------------------------------
    # Devoluciones: la promoción vuelve en proporción
    # ------------------------------------------------------------------
    def _getnet_promocion_de_origen(self):
        """La promoción del pedido que se devuelve, o vacío."""
        self.ensure_one()
        return self.return_origin_order_id.line_ids.getnet_promocion_id[:1]

    def action_create_return(self, line_specs, employee=None, pin=None, reason=None,
                             session_id=None):
        """Con promoción, cada producto devuelto lleva su parte del descuento.

        Con la promoción como línea aparte, una devolución que copia el precio
        de la línea devolvería el precio LLENO: se devolvería plata que el
        cliente nunca pagó. Por cada línea devuelta se agrega su parte de la
        promoción (una línea por línea, con sus impuestos), así el total de la
        devolución es exactamente lo que se pagó por eso. La línea de
        descuento de la venta no se devuelve sola: vuelve en proporción.
        """
        Line = self.env['pos_backend.order.line']
        for spec in line_specs or []:
            if Line.browse(spec.get('line_id')).getnet_promocion_id:
                raise UserError(_(
                    'La línea de la promoción no se devuelve sola: al devolver '
                    'un producto, su parte del descuento se descuenta sola.'))
        devolucion = super().action_create_return(
            line_specs, employee=employee, pin=pin, reason=reason, session_id=session_id)
        promocion = devolucion._getnet_promocion_de_origen()
        if promocion:
            vals = []
            for linea in devolucion.line_ids.filtered(
                    lambda l: l.original_order_line_id and not l.getnet_promocion_id):
                unitario = linea.price_unit * (1 - linea.discount / 100)
                if not unitario:
                    continue
                vals.append({
                    'order_id': devolucion.id,
                    'product_id': promocion.producto_descuento_id.id,
                    'description': _('Promoción %(promo)s (devolución de %(producto)s)',
                                     promo=promocion.name,
                                     producto=linea.description or linea.product_id.name),
                    'quantity': linea.quantity,
                    'qty_to_deliver': 0.0,
                    'price_unit': -unitario * promocion.porcentaje / 100,
                    'tax_ids': [(6, 0, linea.tax_ids.ids)],
                    'is_reward_line': True,
                    'getnet_promocion_id': promocion.id,
                })
            Line.sudo().with_context(pos_backend_authorized=True,
                                     getnet_promo_interno=True).create(vals)
        return devolucion

    def _prepare_return_invoice_line_vals(self, line):
        vals = super()._prepare_return_invoice_line_vals(line)
        if line.getnet_promocion_id:
            vals['getnet_promocion_id'] = line.getnet_promocion_id.id
            vals['account_id'] = line.getnet_promocion_id.cuenta_id.id
        return vals

    def _getnet_tarjeta_restringida(self):
        try:
            return json.loads(self.getnet_promocion_tarjeta or '{}')
        except ValueError:
            return {}


class PosBackendOrderLine(models.Model):
    _inherit = 'pos_backend.order.line'

    getnet_promocion_id = fields.Many2one(
        'getnet.promocion', string='Promoción Getnet', readonly=True,
        copy=False, ondelete='restrict', index='btree_not_null',
        help='La línea es el descuento de esta promoción.')

    def _compute_qty_returned(self):
        super()._compute_qty_returned()
        # La línea de la promoción no se elige para devolver: vuelve en
        # proporción con cada producto devuelto.
        for linea in self.filtered('getnet_promocion_id'):
            linea.qty_returnable = 0.0

    def _getnet_pedidos_a_recalcular(self):
        if self.env.context.get('getnet_promo_interno'):
            return self.env['pos_backend.order']
        return self.filtered(lambda l: not l.getnet_promocion_id).order_id.filtered(
            'getnet_promocion_id')

    @api.model_create_multi
    def create(self, vals_list):
        lineas = super().create(vals_list)
        for order in lineas._getnet_pedidos_a_recalcular():
            order._getnet_rehacer_lineas_promocion()
        return lineas

    def _getnet_check_linea_de_promo(self):
        if self.env.context.get('getnet_promo_interno'):
            return
        if self.filtered('getnet_promocion_id'):
            raise UserError(_(
                'La línea de la promoción no se edita a mano: se rehace sola '
                'cuando cambian los productos. Para sacarla, quitá la promoción.'))

    def write(self, vals):
        if {'quantity', 'price_unit', 'discount', 'tax_ids', 'product_id'} & set(vals):
            self._getnet_check_linea_de_promo()
        res = super().write(vals)
        if {'quantity', 'price_unit', 'discount', 'tax_ids', 'product_id'} & set(vals):
            for order in self._getnet_pedidos_a_recalcular():
                order._getnet_rehacer_lineas_promocion()
        return res

    def unlink(self):
        self._getnet_check_linea_de_promo()
        pedidos = self._getnet_pedidos_a_recalcular()
        res = super().unlink()
        for order in pedidos.exists():
            order._getnet_rehacer_lineas_promocion()
        return res
