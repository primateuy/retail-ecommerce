# -*- coding: utf-8 -*-
"""
Integración Fiserv ITD con el pago contable estándar (account.payment).

Desde **contabilidad** el flujo usa solo ``payment.provider`` (Fiserv) ligado a la
**línea de método de pago** del diario: no se resuelve ni se llama a
``pos.payment.method``. Los PosID salen de ``fiserv.pos.terminal`` del mismo proveedor.

Flujo: «Crear transacción» registra la ``payment.transaction`` y la
consolida ANTES de hablar con ITD, postea al pinpad y lanza un hilo que
consulta hasta la respuesta final. Al aprobar, el pago QUEDA EN BORRADOR y el
usuario Confirma (nunca auto-post). Confirmar sin transacción aprobada, o
volver a borrador / cancelar / rechazar con transacción aprobada, está
bloqueado: la reversión de un cobro aprobado se hace por ticket.
"""

import logging
import threading
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.odoo_pos_fiserv_core.models import fiserv_utils
from odoo.addons.odoo_pos_fiserv_core.models.payment_transaction import (
    FISERV_POLL_HARD_MAX,
    FISERV_RC_EN_CURSO,
)

_logger = logging.getLogger(__name__)

# 19.0: account.payment tiene su PROPIA máquina de estados y el valor
# 'posted' ya no existe. Confirmar deja el pago en 'in_process', o directo
# en 'paid' cuando la cuenta pendiente del método es de caja. Comparar contra
# 'posted' no falla: devuelve False siempre, y la conciliación con las
# facturas origen dejaría de correr en silencio (así estaba en 17.0 → 19.0).
FISERV_PAYMENT_CONFIRMADO = ('in_process', 'paid')

# Un hilo de consultas vive como mucho FISERV_POLL_HARD_MAX. Pasado eso más
# un margen, un «en curso» que sigue marcado es de un proceso que murió
# (reinicio, deploy) y se permite reconsultar.
FISERV_WORKER_STALE = timedelta(seconds=FISERV_POLL_HARD_MAX + 300)


class AccountPayment(models.Model):
    """
    Extiende account.payment para cobrar o devolver en terminal Fiserv desde contabilidad.
    """

    _inherit = 'account.payment'

    # Redefinir para evitar que al duplicar un pago se copie la transacción original
    payment_transaction_id = fields.Many2one(copy=False)

    fiserv_charge_on_pos = fields.Boolean(
        string='Cobrar en terminal Fiserv (ITD)',
        default=False,
        copy=False,
        help='Se marca solo al elegir un método de pago Fiserv: el cobro pasa '
             'por el pinpad vía ITD, sin usar el punto de venta.',
    )
    fiserv_selectable_terminal_ids = fields.Many2many(
        comodel_name='fiserv.pos.terminal',
        compute='_compute_fiserv_terminal_choice_fields',
        string='Terminales Fiserv (técnico)',
    )
    fiserv_need_terminal_choice = fields.Boolean(
        string='Requiere elegir terminal',
        compute='_compute_fiserv_terminal_choice_fields',
    )
    fiserv_terminal_id = fields.Many2one(
        comodel_name='fiserv.pos.terminal',
        string='Terminal Fiserv (PosID)',
        domain="[('id', 'in', fiserv_selectable_terminal_ids)]",
        copy=False,
        ondelete='restrict',
        help='Terminales PosID del proveedor Fiserv de la línea de método de pago del diario.',
    )
    fiserv_original_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción Fiserv original (devolución)',
        # Por el método de pago y no por el proveedor: payment.provider es de
        # Ajustes y un dominio que lo atraviesa no lo puede evaluar el contador.
        domain=(
            "[('payment_method_id.code', '=', 'fiserv'), ('ticket_number', '!=', False), "
            "('company_id', '=', company_id), ('state', '=', 'done'), ('amount', '>', 0)]"
        ),
        copy=False,
        ondelete='restrict',
        help='Cobro Fiserv a anular por ticket; el importe se fija al 100% del cobro.',
    )
    fiserv_async_terminal_pending = fields.Boolean(
        string='Fiserv: operación en curso',
        default=False,
        copy=False,
        help='Evita doble envío mientras el hilo ITD consulta al pinpad.',
    )
    fiserv_async_started_at = fields.Datetime(
        string='Fiserv: inicio de la operación',
        copy=False,
        help='Cuándo arrancó el hilo de consultas; distingue un hilo vivo de '
             'uno que murió con el proceso.',
    )
    fiserv_source_invoice_ids = fields.Many2many(
        comodel_name='account.move',
        # Nombre explícito, igual al que 17.0 generaba por defecto: así una
        # base migrada conserva los datos y otro Many2many pago↔factura con
        # nombre por defecto no puede caer en la misma tabla sin avisar.
        relation='account_move_account_payment_rel',
        column1='account_payment_id',
        column2='account_move_id',
        string='Facturas origen (técnico)',
        copy=False,
        help='Facturas asociadas al pago para calcular TaxRefund ITD y '
        'conciliar al confirmar.',
    )
    fiserv_payment_tx_provider_code = fields.Char(
        string='Código proveedor (transacción)',
        compute='_compute_fiserv_payment_tx_provider_code',
    )
    fiserv_is_fiserv_payment_line = fields.Boolean(
        string='Línea de pago Fiserv (técnico)',
        compute='_compute_fiserv_is_fiserv_payment_line',
    )
    fiserv_is_integrated_journal = fields.Boolean(
        string='Diario con terminal integrada (técnico)',
        compute='_compute_fiserv_is_integrated_journal',
    )
    fiserv_tx_state = fields.Selection(
        related='payment_transaction_id.state',
        string='Estado transacción Fiserv',
        readonly=True,
    )
    fiserv_tx_is_done = fields.Boolean(
        string='Transacción Fiserv aprobada (técnico)',
        compute='_compute_fiserv_tx_flags',
    )
    fiserv_tx_can_requery = fields.Boolean(
        string='Se puede reconsultar (técnico)',
        compute='_compute_fiserv_tx_flags',
        help='La transacción sin resultado tiene TransactionId de ITD: hay a quién preguntarle.',
    )
    fiserv_tx_is_pending = fields.Boolean(
        string='Transacción Fiserv sin resultado (técnico)',
        compute='_compute_fiserv_tx_flags',
        help='Hay una transacción Fiserv enviada al pinpad sin resultado final. '
             'No se puede volver a cobrar hasta reconsultarla.',
    )
    # Flags compartidos con los otros backends de POS integrado (Getnet, OCA):
    # el puente de cada uno suma o neutraliza sus términos acá.
    pos_integrated_post_blocked = fields.Boolean(
        compute='_compute_pos_integrated_flags',
        help='Oculta Confirmar mientras la terminal no haya aprobado el cobro.',
    )
    pos_integrated_cancel_blocked = fields.Boolean(
        compute='_compute_pos_integrated_flags',
        help='Oculta Cancelar con un cobro aprobado o en curso.',
    )
    pos_integrated_draft_blocked = fields.Boolean(
        compute='_compute_pos_integrated_flags',
        help='Oculta Restablecer a borrador con un cobro aprobado o en curso.',
    )

    # ------------------------------------------------------------------
    # Computes / onchange
    # ------------------------------------------------------------------
    @api.depends('payment_method_line_id', 'payment_method_line_id.payment_provider_id')
    def _compute_fiserv_is_fiserv_payment_line(self):
        for pay in self:
            # sudo: payment.provider sólo lo lee base.group_system. Sin sudo el
            # contador no puede ni abrir el form del pago (DL-1 de Getnet, que
            # en Fiserv también estaba). Se lee sólo 'code'.
            provider = pay.payment_method_line_id.payment_provider_id.sudo()
            pay.fiserv_is_fiserv_payment_line = bool(provider and provider.code == 'fiserv')

    @api.depends(
        'journal_id',
        'journal_id.inbound_payment_method_line_ids.payment_provider_id',
        'journal_id.outbound_payment_method_line_ids.payment_provider_id',
    )
    def _compute_fiserv_is_integrated_journal(self):
        for pay in self:
            lines = (
                pay.journal_id.inbound_payment_method_line_ids
                + pay.journal_id.outbound_payment_method_line_ids
            )
            pay.fiserv_is_integrated_journal = any(
                ln.payment_provider_id.sudo().code == 'fiserv'
                for ln in lines if ln.payment_provider_id
            )

    @api.depends('payment_transaction_id', 'payment_transaction_id.state',
                 'payment_transaction_id.fiserv_transaction_id',
                 'payment_transaction_id.fiserv_requiere_conciliacion')
    def _compute_fiserv_tx_flags(self):
        for pay in self:
            tx = pay.payment_transaction_id
            es_fiserv = bool(tx and tx.sudo().provider_id.code == 'fiserv')
            pay.fiserv_tx_is_done = bool(es_fiserv and tx.state == 'done')
            # «Sin resultado» = en vuelo con TransactionId (se puede
            # reconsultar), o marcada para verificar aunque no tenga id (un
            # transporte caído en el POST inicial: sin id no hay a quién
            # preguntarle, pero el cobro pudo existir). En los dos casos no se
            # puede volver a cobrar hasta resolverla.
            pay.fiserv_tx_is_pending = bool(
                es_fiserv and tx.state in ('draft', 'pending')
                and (tx.fiserv_transaction_id or tx.fiserv_requiere_conciliacion))
            pay.fiserv_tx_can_requery = bool(pay.fiserv_tx_is_pending and tx.fiserv_transaction_id)

    @api.depends('payment_transaction_id', 'payment_transaction_id.provider_id')
    def _compute_fiserv_payment_tx_provider_code(self):
        for pay in self:
            tx = pay.payment_transaction_id
            pay.fiserv_payment_tx_provider_code = tx.sudo().provider_id.code if tx else False

    def _fiserv_must_charge_on_terminal(self):
        """
        True si el pago exige pasar por el pinpad y aún no lo hizo.

        Única fuente de verdad del bloqueo de Confirmar (flags de vista y
        guard de action_post). En 17.0 bastaba con que el DIARIO tuviera una
        línea Fiserv para bloquear todo pago del diario; en 19.0 eso es un
        problema nuevo, porque al habilitar el proveedor Odoo le asigna el
        primer diario bancario y todos los pagos manuales de ese banco
        quedarían bloqueados. Manda la línea del pago.
        """
        self.ensure_one()
        return bool(self.fiserv_is_fiserv_payment_line and not self.fiserv_tx_is_done)

    @api.depends(
        'fiserv_async_terminal_pending',
        'fiserv_is_fiserv_payment_line',
        'fiserv_tx_is_done',
        'fiserv_tx_is_pending',
    )
    def _compute_pos_integrated_flags(self):
        """
        Flags de visibilidad compartidos. Mira también los de OCA (vía
        ``_fields``) por si ese backend convive en la base.
        """
        for pay in self:
            f_pending = pay.fiserv_async_terminal_pending or pay.fiserv_tx_is_pending
            f_waiting = pay._fiserv_must_charge_on_terminal()
            f_done = pay.fiserv_tx_is_done

            o_pending = o_waiting = o_done = False
            if 'oca_charge_on_pos' in pay._fields:
                o_pending = pay.oca_async_terminal_pending
                o_waiting = pay.oca_charge_on_pos and not pay.oca_tx_is_done
                o_done = pay.oca_tx_is_done

            pay.pos_integrated_post_blocked = f_pending or f_waiting or o_pending or o_waiting
            pay.pos_integrated_cancel_blocked = f_pending or f_done or o_pending or o_done
            pay.pos_integrated_draft_blocked = f_pending or f_done or o_pending or o_done

    @api.depends('journal_id', 'company_id', 'payment_method_line_id')
    def _compute_fiserv_terminal_choice_fields(self):
        for pay in self:
            provider = pay.payment_method_line_id.payment_provider_id.sudo()
            if not provider or provider.code != 'fiserv':
                pay.fiserv_selectable_terminal_ids = False
                pay.fiserv_need_terminal_choice = False
                continue
            terminals = self.env['fiserv.pos.terminal'].search(
                [('payment_provider_id', '=', provider.id)])
            pay.fiserv_selectable_terminal_ids = terminals
            pay.fiserv_need_terminal_choice = len(terminals) > 0

    @api.onchange('journal_id', 'payment_method_line_id')
    def _onchange_fiserv_auto_charge_integrated_journal(self):
        """
        Método Fiserv: marca el check y preselecciona la terminal única.
        Cualquier otro método: lo DESMARCA. En 17.0 no lo desmarcaba y el
        check quedaba pegado al pasar a otro diario (en una base con Getnet
        eso ocultaba Confirmar para siempre en los pagos Getnet).
        """
        for pay in self:
            if pay.fiserv_is_fiserv_payment_line:
                pay.fiserv_charge_on_pos = True
                terminals = pay.fiserv_selectable_terminal_ids
                if len(terminals) == 1 and not pay.fiserv_terminal_id:
                    pay.fiserv_terminal_id = terminals[0]
            else:
                pay.fiserv_charge_on_pos = False
                pay.fiserv_terminal_id = False
                pay.fiserv_original_transaction_id = False

    @api.onchange('fiserv_original_transaction_id')
    def _onchange_fiserv_original_transaction_id(self):
        """
        Precarga partner, moneda y monto desde la transacción original. Una
        devolución por ticket replica al 100% el cobro original.
        """
        tx = self.fiserv_original_transaction_id
        if not tx:
            return
        if tx.partner_id:
            self.partner_id = tx.partner_id
        if tx.currency_id:
            self.currency_id = tx.currency_id
        if tx.amount:
            self.amount = abs(tx.amount)

    # ------------------------------------------------------------------
    # Datos para ITD
    # ------------------------------------------------------------------
    def _fiserv_backend_fiserv_provider(self):
        """
        Proveedor Fiserv del pago, **exclusivamente** desde la línea de método.

        Devuelto en sudo: payment.provider es de Ajustes y quien opera el flujo
        es un contador; el posteo necesita leer el SystemId. Es la máquina
        actuando en nombre del usuario, acotada a este proveedor.
        """
        self.ensure_one()
        line = self.payment_method_line_id
        prov = line.payment_provider_id.sudo()
        if not line or not prov or prov.code != 'fiserv':
            raise UserError(_(
                'Para cobrar con Fiserv ITD desde contabilidad, el método de pago '
                'del diario «%(journal)s» tiene que ser el del proveedor Fiserv. '
                'Método actual: %(line)s.',
                journal=self.journal_id.display_name,
                line=line.display_name or _('(ninguno)')))
        return prov

    def _fiserv_compute_tax_amount_cents(self):
        """
        TaxAmount (IVA real) en centavos para el payload ITD.

        - Sin facturas o más de 1 → 0.
        - Exactamente 1 → (monto_pago / total_factura) × impuesto_factura.
        """
        self.ensure_one()
        invoices = self.fiserv_source_invoice_ids or self.reconciled_invoice_ids
        if len(invoices) != 1:
            return '0'
        invoice = invoices[0]
        if not invoice.amount_tax or invoice.amount_total == 0:
            return '0'
        ratio = self.amount / invoice.amount_total
        return str(int(round(ratio * invoice.amount_tax * 100)))

    def _fiserv_compute_tax_refund_cents(self):
        """
        TaxRefund en centavos para el payload ITD (misma regla que TaxAmount).
        """
        self.ensure_one()
        invoices = self.fiserv_source_invoice_ids or self.reconciled_invoice_ids
        if len(invoices) != 1:
            return 0
        invoice = invoices[0]
        if not invoice.amount_tax or invoice.amount_total == 0:
            return 0
        ratio = self.amount / invoice.amount_total
        return int(round(ratio * invoice.amount_tax * 100))

    def _fiserv_validate_before_terminal_charge(self, provider):
        """Validaciones antes de llamar a ITD."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Indique el contacto en el pago.'))
        if provider.fiserv_is_multiple and not self.fiserv_terminal_id:
            raise UserError(_('Seleccione el terminal Fiserv (PosID).'))
        if self.payment_type == 'outbound':
            tx_orig = self.fiserv_original_transaction_id
            if not tx_orig:
                raise UserError(_('Indique la transacción Fiserv original a anular por ticket.'))
            if not (tx_orig.ticket_number or '').strip():
                raise UserError(_('La transacción original debe tener ticket ITD.'))
            if tx_orig.currency_id != self.currency_id:
                raise UserError(_('La moneda del pago debe coincidir con la transacción original.'))

    def _fiserv_check_operator(self):
        """
        Guard de los métodos públicos (botones): se llega a ellos por RPC, así
        que ocultar el botón no alcanza. Opera Fiserv quien puede registrar
        pagos (facturación o contabilidad).
        """
        if not self.env.su and not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(_('Solo un usuario de Facturación o Contabilidad puede '
                                'operar la terminal Fiserv.'))

    # ------------------------------------------------------------------
    # Crear transacción
    # ------------------------------------------------------------------
    def action_fiserv_create_transaction(self):
        """
        Botón «Crear transacción»: envía el cobro (o la devolución) al pinpad
        **sin confirmar el pago**.

        La transacción se crea y se consolida ANTES del POST: si el proceso
        muere a mitad, el rastro del cobro existe igual. Un fallo de
        transporte la deja ``pending`` con aviso —jamás ``error``—; un rechazo
        explícito de ITD sí la cierra como ``error``.
        """
        self.ensure_one()
        self._fiserv_check_operator()
        if self.fiserv_async_terminal_pending:
            raise UserError(_(
                'Ya hay una operación Fiserv en curso para este pago. Espere el '
                'resultado antes de reintentar.'))
        if self.state != 'draft':
            raise UserError(_('Solo se pueden crear transacciones Fiserv sobre pagos en borrador.'))
        if self.fiserv_tx_is_done:
            raise UserError(_(
                'Este pago ya tiene una transacción Fiserv aprobada. Pulse «Confirmar».'))
        if self.fiserv_tx_is_pending:
            raise UserError(_(
                'Este pago tiene una transacción Fiserv enviada al pinpad y sin '
                'resultado. NO vuelva a cobrar: use «Reconsultar en ITD» o '
                'verifique el pinpad.'))
        provider = self._fiserv_backend_fiserv_provider()
        provider._fiserv_check_ready()
        self._fiserv_validate_before_terminal_charge(provider)

        if self.payment_type == 'inbound':
            data = provider._prepare_fiserv_itd_payload_for_account_payment(self)
        elif self.payment_type == 'outbound':
            tx_orig = self.fiserv_original_transaction_id
            if self.amount != abs(tx_orig.amount):
                self.write({'amount': abs(tx_orig.amount)})
            data = provider._prepare_fiserv_itd_void_payload_for_account_payment(self, tx_orig)
        else:
            raise UserError(_('Tipo de pago no soportado para terminal Fiserv.'))

        tx = self._fiserv_create_pending_tx(provider, data)
        self.write({
            'payment_transaction_id': tx.id,
            'fiserv_charge_on_pos': True,
            'fiserv_async_terminal_pending': True,
            'fiserv_async_started_at': fields.Datetime.now(),
        })
        fiserv_utils.fiserv_safe_commit(self.env)

        if self.payment_type == 'inbound':
            sent, response = data, provider._fiserv_start_purchase(data)
        else:
            sent, response = provider._fiserv_start_void_or_refund(self, data)
        rc = str(response.get('ResponseCode', '999')).strip()

        if fiserv_utils.fiserv_is_transport_failure(response):
            # 🔴 UN FALLO DE TRANSPORTE NO ES UN RECHAZO. El pedido pudo haber
            # llegado a ITD y haber un cobro vivo en el pinpad. Queda pendiente
            # y marcado para verificar. Sin TransactionId no hay a quién
            # reconsultar: la verificación es contra el pinpad / cierre de lote.
            tx._fiserv_persist_query_result(response, pos_data=sent)
            self._fiserv_clear_pending()
            raise UserError(_(
                'No se pudo confirmar si la operación llegó a la terminal Fiserv '
                '(%(msg)s). NO vuelva a cobrar sin verificar el pinpad: la '
                'transacción quedó registrada como pendiente de verificación.',
                msg=response.get('msg') or ''))
        if rc != '0':
            # ITD CONTESTÓ y dijo que no: no hay nada en el pinpad.
            tx._fiserv_persist_query_result(response, pos_data=sent)
            self._fiserv_clear_pending()
            raise UserError(_('ITD rechazó el inicio: %(c)s — %(m)s',
                              c=rc, m=response.get('msg') or ''))

        transaction_id = str(response.get('TransactionId') or '').strip()
        tx.sudo().write({
            'fiserv_transaction_id': transaction_id,
            'fiserv_complete_request': fiserv_utils.fiserv_mask_payload_json(sent),
        })
        tx._set_pending(state_message=_('Operación enviada al pinpad (ITD %s).', transaction_id))
        fiserv_utils.fiserv_safe_commit(self.env)
        try:
            self._fiserv_start_worker_thread(tx, provider, sent, transaction_id)
        except Exception:
            _logger.exception('Fiserv: no arrancó el hilo de consultas del pago %s', self.id)
            self._fiserv_clear_pending()
            raise UserError(_(
                'La operación se envió al pinpad (ITD %s) pero no arrancó la consulta '
                'del resultado. Use «Reconsultar en ITD».', transaction_id))
        return True

    def _fiserv_create_pending_tx(self, provider, data):
        """La payment.transaction del pago, antes de hablar con ITD."""
        self.ensure_one()
        amount = abs(self.amount)
        if self.payment_type == 'outbound':
            amount = -amount
        reference = 'FISERV-%s-%s' % (self.id, fields.Datetime.now().strftime('%Y%m%d%H%M%S'))
        Tx = self.env['payment.transaction'].sudo()
        if Tx.search_count([('reference', '=', reference)]):
            reference = '%s-%s' % (reference, Tx.search_count([('reference', '=like', reference + '%')]))
        # sudo: la transacción la crea la máquina en nombre del usuario.
        return Tx.create({
            'provider_id': provider.id,
            'payment_method_id': self.env.ref('odoo_pos_fiserv_core.payment_method_fiserv').id,
            'reference': reference,
            'amount': amount,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'account_payment_id': self.id,
            'transaction_origin': 'account_payment',
            'pos_id': data.get('PosID'),
            'invoice_number': data.get('InvoiceNumber') or self.memo or self.name or '',
            'fiserv_complete_request': fiserv_utils.fiserv_mask_payload_json(data),
        })

    def _fiserv_clear_pending(self):
        self.sudo().write({'fiserv_async_terminal_pending': False})
        fiserv_utils.fiserv_safe_commit(self.env)

    # ------------------------------------------------------------------
    # Hilo de consultas
    # ------------------------------------------------------------------
    def _fiserv_start_worker_thread(self, tx, provider, sent_data, transaction_id):
        """Lanza el hilo de consultas con cursor propio."""
        self.ensure_one()
        thread = threading.Thread(
            target=self._fiserv_worker_thread_entry,
            args=(self.env.cr.dbname, self.env.uid, self.id, tx.id, provider.id,
                  dict(sent_data), transaction_id),
            daemon=True,
        )
        thread.start()

    @api.model
    def _fiserv_worker_thread_entry(self, dbname, uid, payment_id, tx_id, provider_id,
                                    sent_data, transaction_id):
        """
        Cuerpo del hilo: cursor propio + worker + limpieza en finally.

        19.0: ``odoo.registry`` YA NO EXISTE (lección del port de Getnet); se
        usa ``odoo.modules.registry.Registry``. El import va adentro para no
        arrastrar el registry al import del módulo.
        """
        from odoo.api import Environment
        from odoo.modules.registry import Registry

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = Environment(cr, uid, {})
            payment = env['account.payment'].browse(payment_id)
            # sudo: el hilo corre con el uid del operador y payment.transaction
            # / payment.provider no son suyos para escribir/leer.
            tx = env['payment.transaction'].sudo().browse(tx_id)
            provider = env['payment.provider'].sudo().browse(provider_id)
            fallo = False
            try:
                payment._fiserv_worker_inner(tx, provider, sent_data, transaction_id)
            except Exception:
                fallo = True
                _logger.exception(
                    'Fiserv: fallo en el hilo del pago %s; la transacción queda '
                    'pendiente y se puede reconsultar.', payment_id)
                # Se descarta lo que el cuerpo dejó a medias. Lo que importa ya
                # estaba consolidado antes del hilo (la transacción pendiente
                # con su TransactionId) o en el commit del cambio void→refund.
                # No es un savepoint a propósito: ese commit intermedio lo
                # liberaría y el RELEASE fallaría.
                cr.rollback()
            finally:
                payment.sudo().write({'fiserv_async_terminal_pending': False})
                if fallo:
                    payment._fiserv_bus_notify(
                        False, _('Error al procesar la respuesta del terminal Fiserv. '
                                 'Use «Reconsultar en ITD».'))
                fiserv_utils.fiserv_safe_commit(env)

    def _fiserv_worker_inner(self, tx, provider, sent_data, transaction_id):
        """
        Lógica del hilo, separada del manejo de cursor para poder ejecutarla
        sincrónicamente en tests. NO confirma el pago: al aprobar queda en
        borrador y el usuario Confirma.
        """
        self.ensure_one()
        query = provider._fiserv_query_payload(sent_data, transaction_id)
        result = tx._fiserv_run_query_loop(
            provider, query, transaction_id, original_purchase_data=sent_data)

        # Void aceptado al inicio pero sin original al consultar (lote cerrado
        # entre la venta y la anulación): se reejecuta como refund.
        if fiserv_utils.fiserv_void_response_needs_refund_fallback(sent_data, result):
            self.message_post(body=_(
                'Fiserv ITD: la anulación no encontró la venta original en el lote '
                'del pinpad (%s); se envía como devolución.',
                tx._get_fiserv_display_message(result)))
            refund_data, refund_resp = provider._fiserv_switch_void_to_refund(self, sent_data)
            refund_rc = str(refund_resp.get('ResponseCode', '999')).strip()
            refund_tid = str(refund_resp.get('TransactionId') or '').strip()
            if refund_rc == '0' and refund_tid:
                tx.write({
                    'fiserv_transaction_id': refund_tid,
                    'fiserv_complete_request': fiserv_utils.fiserv_mask_payload_json(refund_data),
                })
                fiserv_utils.fiserv_safe_commit(self.env)
                sent_data, transaction_id = refund_data, refund_tid
                query = provider._fiserv_query_payload(refund_data, refund_tid)
                result = tx._fiserv_run_query_loop(
                    provider, query, refund_tid, original_purchase_data=refund_data)
            else:
                # Refund rechazado o sin respuesta: se persiste ESO. Un
                # transporte deja la transacción pendiente de verificar.
                sent_data, result = refund_data, refund_resp

        tx._fiserv_persist_query_result(result, pos_data=sent_data)
        self._fiserv_post_result_message(tx)
        self._fiserv_bus_notify(tx.state == 'done', self._fiserv_result_text(tx))
        return result

    def _fiserv_result_text(self, tx):
        if tx.state == 'done':
            return _('El cobro en el terminal fue aprobado. Pulse «Confirmar» para '
                     'registrar el pago.')
        if tx.state == 'pending':
            return _('Sin resultado de ITD: la operación quedó pendiente de verificar. '
                     'NO vuelva a cobrar; use «Reconsultar en ITD».')
        if self.payment_type == 'outbound':
            return _('Fiserv ITD (devolución): la operación no quedó aprobada en el '
                     'terminal. %s', tx.state_message or '')
        return _('Fiserv ITD: el cobro no quedó aprobado en el terminal. %s',
                 tx.state_message or '')

    def _fiserv_post_result_message(self, tx):
        if tx.state == 'done':
            body = _('Fiserv ITD: aprobado en el pinpad (ticket %(t)s, lote %(l)s, '
                     'autorización %(a)s). Pulse «Confirmar» para registrar el pago.',
                     t=tx.ticket_number or '-', l=tx.batch_number or '-',
                     a=tx.authorization_code or '-')
        else:
            body = self._fiserv_result_text(tx)
        self.message_post(body=body)

    def _fiserv_bus_notify(self, posted, message):
        """
        Aviso al navegador del operador para que refresque el form del pago.
        No se puede devolver una acción desde un hilo: va por el bus.
        """
        self.ensure_one()
        user = self.env.user
        if not user.partner_id:
            return
        try:
            self.env['bus.bus'].sudo()._sendone(
                user.partner_id,
                'fiserv_account.payment_refresh',
                {'payment_id': self.id, 'posted': bool(posted), 'message': message or ''},
            )
        except Exception as err:  # noqa: BLE001 - el aviso no puede tumbar el resultado
            _logger.warning('Fiserv: no se pudo enviar el aviso al navegador: %s', err)

    # ------------------------------------------------------------------
    # Reconsultar
    # ------------------------------------------------------------------
    def action_fiserv_requery(self):
        """
        Botón «Reconsultar en ITD»: pregunta UNA vez por una transacción que
        quedó sin resultado (hilo muerto por reinicio, respuesta que no llegó).

        Conservador a propósito: sólo una respuesta FINAL de ITD (RC 0) cambia
        el estado. Si el pinpad sigue en curso, o ITD no contesta, o contesta
        algo que no es un resultado (p.ej. «no existe transacción» para una
        consulta vieja), la transacción sigue pendiente y marcada para
        verificar: nunca se da por fallido un cobro que quizá existió.
        """
        self.ensure_one()
        self._fiserv_check_operator()
        tx = self.payment_transaction_id.sudo()
        if not self.fiserv_tx_is_pending or not tx.fiserv_transaction_id:
            # Sin TransactionId (transporte caído en el POST inicial) no hay a
            # quién preguntarle: se verifica contra el pinpad y se usa
            # «Verificada: sin cobro».
            raise UserError(_('Este pago no tiene una transacción Fiserv pendiente para reconsultar.'))
        if self.fiserv_async_terminal_pending:
            vivo = (self.fiserv_async_started_at
                    and fields.Datetime.now() - self.fiserv_async_started_at < FISERV_WORKER_STALE)
            if vivo:
                raise UserError(_('La consulta automática sigue en curso; espere su resultado.'))
            self.sudo().write({'fiserv_async_terminal_pending': False})
        provider = tx.provider_id
        data = provider._fiserv_identity_payload(tx.pos_id)
        data['TransactionId'] = tx.fiserv_transaction_id
        result = provider._fiserv_itd_query(data)
        rc = str(result.get('ResponseCode', '999')).strip()
        if rc == '0':
            tx._fiserv_persist_query_result(result)
            self._fiserv_post_result_message(tx)
        elif rc in FISERV_RC_EN_CURSO:
            self.message_post(body=_('Fiserv ITD: la operación sigue en curso en el pinpad (%s).',
                                     tx._get_fiserv_display_message(result)))
        else:
            motivo = _('Reconsulta sin resultado final (%(rc)s): %(msg)s',
                       rc=rc, msg=result.get('msg') or '')
            tx._fiserv_marcar_conciliacion(motivo)
            self.message_post(body=_('Fiserv ITD: %s. La transacción sigue pendiente de '
                                     'verificación contra el pinpad o el cierre de lote.', motivo))
        return True

    def action_fiserv_mark_verified(self):
        """«Verificada: sin cobro» desde el pago (delegado en la transacción)."""
        self.ensure_one()
        tx = self.payment_transaction_id
        if not self.fiserv_tx_is_pending or not tx:
            raise UserError(_('Este pago no tiene una transacción Fiserv pendiente.'))
        if self.fiserv_async_terminal_pending:
            raise UserError(_('La consulta automática sigue en curso; espere su resultado.'))
        tx.fiserv_action_conciliada()
        self.message_post(body=_(
            'Fiserv ITD: transacción %s verificada a mano como NO cobrada.', tx.reference))
        return True

    # ------------------------------------------------------------------
    # Bloqueos de post / cancel / draft / reject
    # ------------------------------------------------------------------
    def action_post(self):
        """
        Confirmar. Para pagos con método Fiserv, sólo con transacción aprobada.
        En 17.0 corría en sudo (salteaba reglas por registro, incluidas las
        multicompañía): ya no.
        """
        for pay in self:
            if pay.fiserv_async_terminal_pending or pay.fiserv_tx_is_pending:
                raise UserError(_(
                    'Hay una operación Fiserv sin resultado para %s; espere o '
                    'reconsulte antes de confirmar.', pay.display_name))
            if pay.state == 'draft' and pay._fiserv_must_charge_on_terminal():
                raise UserError(_(
                    'El pago %s debe cobrarse en la terminal Fiserv antes de '
                    'confirmarse: use «Crear transacción» y espere la aprobación.',
                    pay.display_name))
        res = super().action_post()
        self._fiserv_reconcile_with_source_invoices()
        return res

    def _fiserv_block_reversal(self, accion):
        for pay in self:
            if pay.fiserv_tx_is_done:
                raise UserError(_(
                    'No se puede %(accion)s el pago %(pago)s: ya fue cobrado en la '
                    'terminal Fiserv. Para devolver el dinero cree un pago «Enviar '
                    'dinero» y seleccione la transacción original.',
                    accion=accion, pago=pay.display_name))
            if pay.fiserv_async_terminal_pending or pay.fiserv_tx_is_pending:
                raise UserError(_(
                    'Hay una operación Fiserv sin resultado para %s.', pay.display_name))

    def action_draft(self):
        self.filtered(lambda p: p.state != 'draft')._fiserv_block_reversal(_('restablecer a borrador'))
        return super().action_draft()

    def action_cancel(self):
        self._fiserv_block_reversal(_('cancelar'))
        return super().action_cancel()

    def action_reject(self):
        """
        «Rechazar», puerta NUEVA de 19.0: lleva el pago a 'rejected' sin pasar
        por la terminal, o sea otra forma de revertir un cobro aprobado sin
        anulación. Se cierra con el mismo criterio que Cancelar. En la vista
        el botón del core sólo aparece con ``is_sent``; el guard existe para
        que tampoco entre por RPC.
        """
        self._fiserv_block_reversal(_('rechazar'))
        return super().action_reject()

    # ------------------------------------------------------------------
    # Conciliación con las facturas origen
    # ------------------------------------------------------------------
    @staticmethod
    def _fiserv_open_receivable_lines(move):
        """
        Apuntes de deudores/acreedores del asiento, sin conciliar. Recibe un
        account.move: en 19.0 el pago dejó de ser ``_inherits`` del asiento y
        ``pay.line_ids`` no existe; se entra por ``pay.move_id``.
        """
        return move.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
            and not l.reconciled)

    def _fiserv_reconcile_with_source_invoices(self):
        """
        Concilia el pago confirmado con sus facturas origen.

        Corre dentro de action_post, con el cobro YA APROBADO en el pinpad:
        un error acá no puede abortar la confirmación. Lo que no se puede
        emparejar queda en el chatter para conciliar a mano.
        """
        for pay in self:
            if not pay.fiserv_source_invoice_ids or pay.state not in FISERV_PAYMENT_CONFIRMADO:
                continue
            pendientes = pay.env['account.move']
            for move in pay.fiserv_source_invoice_ids.filtered(lambda m: m.state == 'posted'):
                lines = pay._fiserv_open_receivable_lines(pay.move_id)
                move_lines = pay._fiserv_open_receivable_lines(move)
                propias = lines.filtered(lambda l: l.account_id in move_lines.account_id)
                ajenas = move_lines.filtered(lambda l: l.account_id in propias.account_id)
                if not propias or not ajenas:
                    pendientes |= move
                    continue
                try:
                    with pay.env.cr.savepoint():
                        (propias + ajenas).reconcile()
                except UserError:
                    _logger.exception(
                        'Fiserv: no se pudo conciliar el pago %s con la factura %s.',
                        pay.display_name, move.display_name)
                    pendientes |= move
            if pendientes:
                pay.message_post(body=_(
                    'El cobro Fiserv quedó registrado, pero no se pudo conciliar '
                    'automáticamente con %(facturas)s. Concílielo a mano desde la factura.',
                    facturas=', '.join(pendientes.mapped('display_name'))))
