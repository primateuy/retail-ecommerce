import json
import logging
from datetime import datetime, timezone

import psycopg2
import requests

from odoo import SUPERUSER_ID, _, fields, models

_logger = logging.getLogger(__name__)

MP_API_URL = 'https://api.mercadopago.com'
MP_TIMEOUT = 10


class MpPendingOrder(models.Model):
    """Orden de PdV esperando el pago de Mercado Pago.

    Guarda los datos del pedido mientras el cliente paga el QR. Cuando MP
    confirma el pago (webhook o botón "Comprobar pago") se convierte en un
    pos.order y el registro pendiente se elimina.
    """

    _name = 'mp.pending.order'
    _description = 'MercadoPago Pending Order'

    name = fields.Char(string='External Reference', required=True, index=True)
    session_id = fields.Many2one(
        'pos.session',
        string='POS Session',
        required=True,
        ondelete='cascade',
    )
    till_id = fields.Many2one(
        'store.tills',
        string='Caja MP',
        ondelete='set null',
    )
    order_data = fields.Text(string='Order Data', required=True)

    # -------------------------------------------------------------------------
    # Comunicación con Mercado Pago
    # -------------------------------------------------------------------------

    def _get_mp_user(self):
        """Devuelve el usuario MP dueño de la caja donde se generó el QR.

        Returns:
            mercado_pago.user: usuario de la sucursal de la caja o, si la orden
                no tiene caja (órdenes viejas), el primero configurado.
        """
        self.ensure_one()
        # sudo: el access_token es solo de base.group_system y lo usa el cajero o el webhook público.
        mp_user = self.sudo().till_id.store_branch_id.mp_user_id
        return mp_user or self.env['mercado_pago.user'].sudo().search([], limit=1)

    def _mp_request(self, method, url, mp_user=None, **kwargs):
        """Hace una request a la API de MP con el token del usuario indicado.

        Usa mercado_pago.user._make_request, que refresca el token y reintenta
        ante un 401. Sin usuario, usa el token del parámetro de sistema.

        Args:
            method (str): método HTTP ('get', 'post', 'delete').
            url (str): URL completa del endpoint.
            mp_user (mercado_pago.user): usuario MP (con sudo) cuyo token se usa.
            **kwargs: argumentos extra para requests.

        Returns:
            requests.Response: respuesta de Mercado Pago.
        """
        kwargs.setdefault('timeout', MP_TIMEOUT)
        if mp_user:
            return mp_user._make_request(method, url, **kwargs)
        # sudo: el token por defecto vive en un parámetro protegido.
        token = self.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value
        kwargs.setdefault('headers', {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        })
        return getattr(requests, method)(url, **kwargs)

    def _find_approved_payment(self):
        """Busca en MP un pago aprobado para la referencia de esta orden.

        Returns:
            dict|bool: el pago de MP aprobado más reciente, o False si no hay.

        Raises:
            requests.RequestException: si MP no responde o responde con error.
        """
        self.ensure_one()
        response = self._mp_request(
            'get',
            f'{MP_API_URL}/v1/payments/search',
            mp_user=self._get_mp_user(),
            params={
                'external_reference': self.name,
                'sort': 'date_created',
                'criteria': 'desc',
            },
        )
        response.raise_for_status()
        for payment in response.json().get('results', []):
            if payment.get('status') == 'approved':
                return payment
        return False

    def _get_merchant_order_status(self):
        """Devuelve el estado de la merchant order de MP para esta referencia.

        Returns:
            str|bool: 'opened', 'closed', 'expired' o False si MP no la tiene.

        Raises:
            requests.RequestException: si MP no responde o responde con error.
        """
        self.ensure_one()
        response = self._mp_request(
            'get',
            f'{MP_API_URL}/merchant_orders',
            mp_user=self._get_mp_user(),
            params={'external_reference': self.name},
        )
        response.raise_for_status()
        elements = response.json().get('elements', [])
        return elements[0].get('status') if elements else False

    def _cancel_mp_order(self, collector_id=None, external_pos_id=None):
        """Quita la orden del QR de la caja en MP.

        Args:
            collector_id (str): user_id MP de la caja, si la orden no tiene caja.
            external_pos_id (str): external_id de la caja, si la orden no tiene caja.

        Returns:
            bool: True si MP aceptó la baja.
        """
        self.ensure_one()
        collector_id = self.till_id.user_id_mp or collector_id
        external_pos_id = self.till_id.external_id or external_pos_id
        url = (
            f'{MP_API_URL}/instore/qr/seller/collectors'
            f'/{collector_id}/pos/{external_pos_id}/orders'
        )
        try:
            response = self._mp_request('delete', url, mp_user=self._get_mp_user())
        except requests.RequestException:
            _logger.exception("No se pudo eliminar la orden %s en Mercado Pago", self.name)
            return False
        if response.status_code >= 400:
            _logger.warning(
                "Mercado Pago devolvio %s al eliminar la orden %s: %s",
                response.status_code, self.name, response.text,
            )
            return False
        return True

    def _reconcile_with_mp(self):
        """Consulta MP y, si el pago ya está aprobado, crea el pos.order.

        Permite registrar el pedido aunque el webhook no haya llegado o haya
        fallado, que es lo que dejaba la caja trabada.

        Returns:
            tuple(str, pos.order): estado ('paid', 'processing', 'pending',
                'expired' o 'error') y el pedido creado (o vacío).
        """
        self.ensure_one()
        try:
            payment = self._find_approved_payment()
            if not payment:
                mp_status = self._get_merchant_order_status()
        except (requests.RequestException, ValueError):
            _logger.exception("Error consultando el estado en MP de la orden %s", self.name)
            return 'error', self.env['pos.order']
        if payment:
            order = self._create_pos_order_from_mp(payment)
            return ('paid' if order else 'processing'), order
        if mp_status == 'closed':
            return 'processing', self.env['pos.order']
        if mp_status == 'expired':
            return 'expired', self.env['pos.order']
        return 'pending', self.env['pos.order']

    # -------------------------------------------------------------------------
    # Creación del pos.order
    # -------------------------------------------------------------------------

    def _lock_for_processing(self):
        """Bloquea el registro para que dos procesos no creen el mismo pedido.

        MP manda notificaciones 'payment' y 'merchant_order' casi a la vez, y
        además el cajero puede apretar "Comprobar pago". SQL crudo porque el
        ORM de Odoo 17 no expone FOR UPDATE NOWAIT; el savepoint evita que el
        fallo del lock aborte la transacción.

        Returns:
            bool: True si se obtuvo el lock.
        """
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    'SELECT id FROM mp_pending_order WHERE id = %s FOR UPDATE NOWAIT',
                    (self.id,),
                )
        except (psycopg2.errors.LockNotAvailable, psycopg2.errors.SerializationFailure):
            return False
        return True

    def _create_pos_order_from_mp(self, payment=None):
        """Crea y confirma el pos.order a partir de esta orden pendiente.

        Es idempotente: si el pedido ya existe lo devuelve, y si otro proceso
        lo está creando devuelve un recordset vacío. Al terminar elimina el
        registro pendiente.

        Args:
            payment (dict): pago aprobado de MP (puede faltar si la
                notificación fue una merchant_order sin pagos).

        Returns:
            pos.order: el pedido creado o existente; vacío si está en proceso.
        """
        self.ensure_one()
        # sudo: se ejecuta desde el webhook público o por un cajero sin permisos de backend.
        pos_order_model = self.env['pos.order'].sudo()
        existing_order = pos_order_model.search([('name', '=', self.name)], limit=1)
        if existing_order:
            return existing_order
        if not self._lock_for_processing():
            _logger.info("Orden MP %s ya esta siendo procesada por otro proceso", self.name)
            return pos_order_model

        order_data = json.loads(self.order_data)
        payment_date = self._get_payment_date(payment)
        order = pos_order_model.create(self._prepare_pos_order_vals(order_data, payment_date))
        self._update_order_amounts(order, order_data)
        self._check_mp_amount(order, payment)
        self._confirm_pos_order(order)
        self._create_payment_transaction(order, payment)
        self.sudo().unlink()
        return order

    def _get_payment_date(self, payment):
        """Devuelve la fecha del pago de MP en UTC, en formato de Odoo."""
        if payment and payment.get('date_created'):
            payment_datetime = datetime.fromisoformat(payment['date_created'])
            if payment_datetime.tzinfo:
                payment_datetime = payment_datetime.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            payment_datetime = datetime.now()
        return fields.Datetime.to_string(payment_datetime)

    def _get_mp_payment_method(self):
        """Devuelve el pos.payment.method de Mercado Pago de la sesión."""
        self.ensure_one()
        payment_method = self.session_id.config_id.payment_method_ids.filtered(
            lambda method: method.use_payment_terminal == 'mercado_pago'
        )[:1]
        return payment_method or self.env['pos.payment.method'].sudo().search(
            [('use_payment_terminal', '=', 'mercado_pago')], limit=1
        )

    def _prepare_pos_order_vals(self, order_data, payment_date):
        """Arma los valores del pos.order a partir de los datos guardados.

        Si hubo vuelto en efectivo, lo registra como pago negativo 'is_change',
        igual que el core en pos.order._process_payment_lines.

        Args:
            order_data (dict): datos guardados al generar el QR.
            payment_date (str): fecha del pago.

        Returns:
            dict: valores para pos.order.create.
        """
        self.ensure_one()
        session = self.session_id
        currency = session.currency_id
        amount_total = order_data.get('amount_total', 0)
        amount_return = order_data.get('amount_return') or 0
        partner_id = order_data.get('partner_id') or False

        payment_lines = order_data.get('payment_lines') or [{
            'amount': amount_total,
            'payment_method_id': self._get_mp_payment_method().id,
        }]
        payment_vals = [
            (0, 0, {
                'amount': line['amount'],
                'payment_method_id': line['payment_method_id'],
                'payment_date': payment_date,
            })
            for line in payment_lines
            if not currency.is_zero(line['amount'])
        ]
        if not currency.is_zero(amount_return):
            cash_method = session.payment_method_ids.filtered('is_cash_count')[:1]
            if cash_method:
                payment_vals.append((0, 0, {
                    'name': _("return"),
                    'amount': -amount_return,
                    'payment_method_id': cash_method.id,
                    'payment_date': payment_date,
                    'is_change': True,
                }))
            else:
                _logger.warning(
                    "Orden MP %s con vuelto %s pero la sesion no tiene metodo en efectivo",
                    self.name, amount_return,
                )

        vals = {
            'name': self.name,
            'pos_reference': self.name,
            'session_id': session.id,
            'user_id': order_data.get('user_id'),
            'employee_id': order_data.get('employee_id') or False,
            'partner_id': partner_id,
            'amount_tax': order_data.get('amount_tax', 0),
            'amount_total': amount_total,
            'amount_paid': amount_total,
            'amount_return': amount_return,
            'company_id': order_data.get('company_id'),
            'to_invoice': bool(partner_id),
            'lines': [(0, 0, line) for line in order_data.get('lines', [])],
            'payment_ids': payment_vals,
        }
        if 'order_salesperson_id' in self.env['pos.order']._fields:
            vals['order_salesperson_id'] = order_data.get('cashier_id') or False
        return vals

    def _update_order_amounts(self, order, order_data):
        """Recalcula subtotales de líneas e importes del pedido.

        Los subtotales que llegan del POS no contemplan cantidad ni descuento,
        así que se recalculan con el core. El total queda como lo calculó el
        POS (igual que en _process_order) y lo pagado es la suma real de pagos.
        """
        order.lines._onchange_amount_line_all()
        currency = order.currency_id
        lines_total = sum(order.lines.mapped('price_subtotal_incl'))
        lines_untaxed = sum(order.lines.mapped('price_subtotal'))
        order.write({
            'amount_tax': currency.round(lines_total - lines_untaxed),
            'amount_total': currency.round(order_data.get('amount_total') or lines_total),
            'amount_paid': currency.round(sum(order.payment_ids.mapped('amount'))),
        })

    def _check_mp_amount(self, order, payment):
        """Avisa en el log si MP cobró distinto de lo que dice la línea de MP."""
        if not payment or payment.get('transaction_amount') is None:
            return
        mp_payments = order.payment_ids.filtered(
            lambda line: line.payment_method_id.use_payment_terminal == 'mercado_pago'
        )
        expected_amount = sum(mp_payments.mapped('amount'))
        if not order.currency_id.is_zero(payment['transaction_amount'] - expected_amount):
            _logger.warning(
                "Orden MP %s: MP cobro %s pero la linea de MP es de %s",
                order.name, payment['transaction_amount'], expected_amount,
            )

    def _confirm_pos_order(self, order):
        """Marca el pedido como pagado y genera picking y factura.

        Cada paso va en su propio savepoint: si falla, el pedido igual queda
        registrado (en borrador si no cuadra el pago) en vez de perderse todo
        el webhook por una transacción abortada.
        """
        try:
            with self.env.cr.savepoint():
                order.action_pos_order_paid()
        except Exception:
            _logger.exception(
                "Orden MP %s creada pero no se pudo marcar como pagada; queda en borrador",
                order.name,
            )
            return

        try:
            with self.env.cr.savepoint():
                # Superusuario: el webhook corre como público y el picking valida stock de otras compañías/ubicaciones.
                su_order = self.env['pos.order'].with_user(SUPERUSER_ID).browse(order.id)
                su_order._create_order_picking()
                pickings = su_order.picking_ids.filtered(
                    lambda picking: picking.state not in ('done', 'cancel')
                )
                for picking in pickings:
                    for move_line in picking.move_line_ids:
                        move_line.quantity = move_line.quantity_product_uom
                    picking.with_context(skip_immediate=True, skip_backorder=True)._action_done()
        except Exception:
            _logger.exception("Error al crear/validar picking para orden %s", order.name)

        if order.to_invoice and order.partner_id:
            try:
                with self.env.cr.savepoint():
                    order._generate_pos_order_invoice()
            except Exception:
                _logger.exception("Error al crear factura para orden %s", order.name)

    def _create_payment_transaction(self, order, payment):
        """Registra el payment.transaction del cobro de MP asociado al pedido."""
        try:
            with self.env.cr.savepoint():
                transaction_model = self.env['payment.transaction'].sudo()
                mp_provider = self.env['payment.provider'].sudo().search([
                    ('code', '=', 'mercado_pago'),
                    ('company_id', '=', order.company_id.id),
                ], limit=1)
                mp_payment_method = self.env.ref(
                    'pos_mercadopago.payment_method_mercado_pago', raise_if_not_found=False
                )
                pos_payment = order.payment_ids.filtered(
                    lambda line: line.payment_method_id.use_payment_terminal == 'mercado_pago'
                )[:1]
                mp_payment_id = str(payment.get('id', '')) if payment else ''
                partner = order.partner_id or order.company_id.partner_id

                tx_vals = {
                    'reference': f"MP-{mp_payment_id or self.name}",
                    'provider_id': mp_provider.id,
                    'payment_method_id': mp_payment_method.id if mp_payment_method else False,
                    'amount': pos_payment.amount if pos_payment else order.amount_total,
                    'currency_id': order.currency_id.id,
                    'partner_id': partner.id,
                    'company_id': order.company_id.id,
                    'state': 'done',
                    'provider_reference': mp_payment_id,
                }
                if 'pos_order_ids' in transaction_model._fields:
                    tx_vals['pos_order_ids'] = [(4, order.id)]
                if 'pos_order_id' in transaction_model._fields:
                    tx_vals['pos_order_id'] = order.id
                if pos_payment and 'pos_payment_id' in transaction_model._fields:
                    tx_vals['pos_payment_id'] = pos_payment.id
                if pos_payment and 'transaction_origin' in transaction_model._fields:
                    tx_vals['transaction_origin'] = 'pos_payment'

                transaction = transaction_model.create(tx_vals)
                if pos_payment and 'payment_transaction_id' in pos_payment._fields:
                    pos_payment.payment_transaction_id = transaction.id
        except Exception:
            _logger.exception("Error al crear payment.transaction para orden %s", order.name)
