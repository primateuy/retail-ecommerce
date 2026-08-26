# -*- coding: utf-8 -*-
"""
Flujo contable Getnet/TransAct sobre account.payment.

UX espejo de Fiserv: «Crear transacción» postea al concentrador y lanza el
worker de polling; al aprobar el pago QUEDA EN BORRADOR y el usuario
Confirma (nunca auto-post). Confirmar sin transacción aprobada, o volver a
borrador / cancelar con transacción aprobada, están bloqueados: la
reversión de un cobro aprobado se hace con una devolución (DEV +
TicketOriginal), no desde el form.
"""

import logging
import threading

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils

_logger = logging.getLogger(__name__)

GETNET_FACTURA_NRO_SIN_FACTURA = getnet_utils.GETNET_FACTURA_NRO_SIN_FACTURA

# Tipos de CFE que corresponden a consumidor final (e-Ticket y sus notas)
GETNET_CFE_CONSUMIDOR_FINAL = (
    '101', '102', '103', '131', '132', '133', '151', '152', '153')


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    getnet_charge_on_pos = fields.Boolean(
        string='Cobrar en terminal Getnet',
        copy=False,
        help='Postea el cobro al POS Getnet vía TransAct al crear la '
             'transacción.',
    )
    getnet_terminal_id = fields.Many2one(
        comodel_name='getnet.pos.terminal',
        string='Terminal Getnet',
        copy=False,
    )
    getnet_selectable_terminal_ids = fields.Many2many(
        comodel_name='getnet.pos.terminal',
        compute='_compute_getnet_selectable_terminals',
        string='Terminales disponibles',
    )
    getnet_need_terminal_choice = fields.Boolean(
        compute='_compute_getnet_selectable_terminals',
    )
    getnet_async_terminal_pending = fields.Boolean(
        string='Esperando terminal Getnet',
        copy=False,
        help='Hay un worker de polling en curso para este pago.',
    )
    getnet_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción Getnet',
        copy=False,
        readonly=True,
    )
    getnet_original_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción original (devolución)',
        copy=False,
        domain="[('provider_code', '=', 'getnet'), ('state', '=', 'done')]",
        help='Transacción aprobada a devolver: se envía DEV con su '
             'TicketOriginal.',
    )
    getnet_source_invoice_ids = fields.Many2many(
        comodel_name='account.move',
        relation='getnet_payment_invoice_rel',
        string='Facturas origen (Getnet)',
        copy=False,
        help='Facturas que cubre el cobro. Con UNA sola factura el posteo '
             'lleva su FacturaNro y los montos (gravado, IVA, consumidor '
             'final) que alimentan la devolución de IVA de la ley 19210; '
             'sin factura o con varias va FacturaNro=0. Al confirmar, el '
             'pago se concilia con ellas.',
    )
    getnet_is_getnet_payment_line = fields.Boolean(
        compute='_compute_getnet_is_getnet_payment_line',
    )
    getnet_is_integrated_journal = fields.Boolean(
        compute='_compute_getnet_is_integrated_journal',
    )
    getnet_tx_is_done = fields.Boolean(
        compute='_compute_getnet_tx_is_done',
    )
    getnet_tx_state = fields.Selection(
        related='getnet_transaction_id.state',
        string='Estado transacción Getnet',
    )
    # Flags de visibilidad PROPIOS de Getnet: el módulo tiene que ocultar
    # Confirmar / Cancelar / Restablecer a borrador por sí mismo, sin
    # depender de los flags pos_integrated_* que define Fiserv (en una
    # instalación standalone de Getnet ese módulo no existe). La
    # convivencia con Fiserv la resuelve odoo_pos_getnet_fiserv_flags.
    getnet_post_blocked = fields.Boolean(
        compute='_compute_getnet_button_guards',
        help='Oculta Confirmar mientras la terminal Getnet no haya '
             'aprobado el cobro (o haya un worker en curso).',
    )
    getnet_cancel_blocked = fields.Boolean(
        compute='_compute_getnet_button_guards',
        help='Oculta Cancelar con un cobro Getnet aprobado o en curso: '
             'la reversión se hace por devolución con ticket.',
    )
    getnet_draft_blocked = fields.Boolean(
        compute='_compute_getnet_button_guards',
        help='Oculta Restablecer a borrador con un cobro Getnet aprobado '
             'o en curso.',
    )

    # ------------------------------------------------------------------
    # Computes / onchange
    # ------------------------------------------------------------------
    @api.depends('payment_method_line_id',
                 'payment_method_line_id.payment_provider_id')
    def _compute_getnet_is_getnet_payment_line(self):
        for pay in self:
            provider = pay.payment_method_line_id.payment_provider_id
            pay.getnet_is_getnet_payment_line = bool(
                provider and provider.code == 'getnet')

    @api.depends('journal_id',
                 'journal_id.inbound_payment_method_line_ids.payment_provider_id',
                 'journal_id.outbound_payment_method_line_ids.payment_provider_id')
    def _compute_getnet_is_integrated_journal(self):
        for pay in self:
            lines = (pay.journal_id.inbound_payment_method_line_ids
                     + pay.journal_id.outbound_payment_method_line_ids)
            pay.getnet_is_integrated_journal = any(
                ln.payment_provider_id.code == 'getnet'
                for ln in lines if ln.payment_provider_id)

    @api.depends('getnet_transaction_id', 'getnet_transaction_id.state')
    def _compute_getnet_tx_is_done(self):
        for pay in self:
            pay.getnet_tx_is_done = bool(
                pay.getnet_transaction_id
                and pay.getnet_transaction_id.state == 'done')

    def _getnet_must_charge_on_terminal(self):
        """True si el pago exige pasar por el pinpad y aún no lo hizo.

        Única fuente de verdad de la condición de bloqueo de Confirmar:
        la usan el compute de los flags de vista y el guard de action_post.
        """
        self.ensure_one()
        obligado = self.getnet_charge_on_pos or (
            self.getnet_is_getnet_payment_line
            and self.getnet_is_integrated_journal)
        return bool(obligado and not self.getnet_tx_is_done)

    @api.depends('getnet_async_terminal_pending', 'getnet_charge_on_pos',
                 'getnet_is_getnet_payment_line',
                 'getnet_is_integrated_journal', 'getnet_tx_is_done')
    def _compute_getnet_button_guards(self):
        """Espejo en la vista de los bloqueos de post / cancel / draft."""
        for pay in self:
            pendiente = pay.getnet_async_terminal_pending
            aprobada = pay.getnet_tx_is_done
            pay.getnet_post_blocked = (
                pendiente or pay._getnet_must_charge_on_terminal())
            pay.getnet_cancel_blocked = pendiente or aprobada
            pay.getnet_draft_blocked = pendiente or aprobada

    @api.depends('journal_id', 'payment_method_line_id')
    def _compute_getnet_selectable_terminals(self):
        for pay in self:
            provider = pay._getnet_provider()
            terminals = provider.getnet_terminal_ids if provider else \
                self.env['getnet.pos.terminal']
            pay.getnet_selectable_terminal_ids = terminals
            pay.getnet_need_terminal_choice = bool(
                provider and provider.getnet_is_multiple
                and len(terminals) > 1)

    @api.onchange('journal_id', 'payment_method_line_id')
    def _onchange_getnet_auto_charge_integrated_journal(self):
        """Diario Getnet: marca el check y preselecciona terminal única."""
        for pay in self:
            provider = pay._getnet_provider()
            if provider:
                pay.getnet_charge_on_pos = True
                terminals = provider.getnet_terminal_ids
                if len(terminals) == 1:
                    pay.getnet_terminal_id = terminals
            else:
                pay.getnet_charge_on_pos = False
                pay.getnet_terminal_id = False

    @api.onchange('getnet_original_transaction_id')
    def _onchange_getnet_original_transaction(self):
        """Precarga datos de la transacción original en la devolución."""
        for pay in self:
            tx = pay.getnet_original_transaction_id
            if tx:
                pay.amount = tx.amount
                pay.currency_id = tx.currency_id
                if tx.partner_id:
                    pay.partner_id = tx.partner_id

    def _getnet_provider(self):
        """Proveedor Getnet resuelto SOLO desde la línea de método de pago."""
        self.ensure_one()
        provider = self.payment_method_line_id.payment_provider_id
        if provider and provider.code == 'getnet':
            return provider
        return self.env['payment.provider']

    def _getnet_terminal(self, provider):
        self.ensure_one()
        if self.getnet_terminal_id:
            return self.getnet_terminal_id
        terminals = provider.getnet_terminal_ids
        if len(terminals) == 1:
            return terminals
        raise UserError(_(
            'Seleccione la terminal Getnet en la que se realizará la '
            'operación.'))

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def _getnet_factura_vals_from_move(self, move):
        """
        Propiedades de Factura del posteo TransAct desde el CFE origen:
        FacturaNro (número del CFE, sin serie), FacturaMonto /
        FacturaMontoGravado / FacturaMontoIVA (anexo del manual general;
        alimentan la devolución de IVA ley 19210) y FacturaConsumidorFinal
        según el tipo de CFE (e-Ticket => consumidor final).
        """
        self.ensure_one()
        lineas = [
            (line.price_subtotal, line.price_total - line.price_subtotal)
            for line in move.invoice_line_ids
            if line.display_type == 'product'
        ]
        vals = getnet_utils.getnet_montos_factura(lineas)
        numero = move.numero_cfe()
        if not numero:
            raise UserError(_(
                'La factura %s no tiene número de CFE asignado; no se '
                'puede enviar a la terminal Getnet.', move.display_name))
        # FacturaNro es numérico en el contrato (xs:double): un valor con
        # letras o separadores lo descartaría WCF en silencio.
        try:
            vals['FacturaNro'] = getnet_utils.getnet_entero_contrato(
                numero, 'FacturaNro')
        except ValueError:
            raise UserError(_(
                'El número de CFE de la factura %(factura)s no es numérico '
                '(%(numero)s) y TransAct exige FacturaNro numérico.',
                factura=move.display_name, numero=numero))
        vals['FacturaConsumidorFinal'] = (
            move.cfe_type in GETNET_CFE_CONSUMIDOR_FINAL)
        return vals

    def _getnet_prepare_transaccion_vals(self, provider, terminal):
        """Payload completo de PostearTransaccion para este pago."""
        self.ensure_one()
        vals = provider._getnet_base_transaccion_vals(terminal)
        vals['MonedaISO'] = provider._getnet_moneda_iso(self.currency_id)
        if self.payment_type == 'outbound':
            tx_orig = self.getnet_original_transaction_id
            vals['Operacion'] = getnet_utils.GETNET_OPERACION_DEVOLUCION
            # TicketOriginal es xs:int en el contrato, pero el Ticket llega
            # en la respuesta como xs:double y se persiste como texto.
            try:
                vals['TicketOriginal'] = getnet_utils.getnet_entero_contrato(
                    tx_orig.getnet_ticket, 'TicketOriginal')
            except ValueError:
                raise UserError(_(
                    'La transacción original %s no tiene un número de ticket '
                    'válido (%s); no se puede enviar la devolución.',
                    tx_orig.reference, tx_orig.getnet_ticket))
            vals['Monto'] = getnet_utils.getnet_centavos(tx_orig.amount)
        else:
            vals['Operacion'] = getnet_utils.GETNET_OPERACION_VENTA
            vals['Monto'] = getnet_utils.getnet_centavos(self.amount)
            # Criterio de FacturaNro (New Age Data, 17/8/2026): el cobro
            # opera desde el pago, con o sin factura. Con UNA factura
            # origen se mandan todos los Factura*.
            #
            # Sin factura o con varias se manda FacturaNro=0 y se omite el
            # resto. El WSDL declara FacturaNro con minOccurs="0", pero el
            # concentrador lo exige a nivel funcional: omitirlo devuelve
            # rc=2 'CAMPO REQUERIDO / VERIFIQUE / FACTURA' (verificado
            # contra el ambiente de integración el 17/8/2026). El 0 sí es
            # aceptado; FacturaMonto/Gravado/IVA/ConsumidorFinal son
            # opcionales de verdad y se omiten.
            facturas = self.getnet_source_invoice_ids
            if len(facturas) == 1:
                vals.update(self._getnet_factura_vals_from_move(facturas))
            else:
                vals['FacturaNro'] = GETNET_FACTURA_NRO_SIN_FACTURA
                if facturas:
                    _logger.info(
                        'Getnet: el pago %s cubre %s facturas; se postea con '
                        'FacturaNro=0 y sin montos de factura (no hay '
                        'FacturaNro único).',
                        self.display_name, len(facturas))
        if provider.getnet_modo_emulacion:
            vals['Configuracion'] = {'ModoEmulacion': True}
        # DecretoLeyId NO se setea: comportamiento recomendado del manual,
        # el POS se lo solicita al cajero.
        return vals

    def _getnet_validate_before_charge(self, provider):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('El pago debe estar en borrador.'))
        if self.getnet_async_terminal_pending:
            raise UserError(_(
                'Ya hay una operación de terminal en curso para este pago.'))
        if self.getnet_tx_is_done:
            raise UserError(_(
                'Este pago ya tiene una transacción Getnet aprobada.'))
        if not self.partner_id:
            raise UserError(_('El pago debe tener un contacto.'))
        # Multi-factura ya NO bloquea: se postea sin datos de factura
        # (criterio de New Age Data del 17/8/2026, mismo que Fiserv).
        # TODO-homologación: queda por confirmar en homologación si la
        # devolución de IVA (ley 19210) exige los Factura* para el
        # consumidor final; si así fuera, habría que resolver un criterio
        # de prorrateo o volver a exigir una factura por pago.
        provider._getnet_moneda_iso(self.currency_id)
        if self.payment_type == 'outbound':
            tx_orig = self.getnet_original_transaction_id
            if not tx_orig or not tx_orig.getnet_ticket:
                raise UserError(_(
                    'Para una devolución Getnet debe seleccionar la '
                    'transacción original aprobada (con ticket).'))
            if tx_orig.currency_id != self.currency_id:
                raise UserError(_(
                    'La devolución debe emitirse en la moneda de la '
                    'transacción original (%s).', tx_orig.currency_id.name))

    # ------------------------------------------------------------------
    # Acción principal
    # ------------------------------------------------------------------
    def action_getnet_create_transaction(self):
        self.ensure_one()
        provider = self._getnet_provider()
        if not provider:
            raise UserError(_(
                'El método de pago del diario no está vinculado a un '
                'proveedor Getnet.'))
        if not self.getnet_charge_on_pos:
            raise UserError(_(
                'Marque «Cobrar en terminal Getnet» para enviar el cobro '
                'al POS.'))
        self._getnet_validate_before_charge(provider)
        terminal = self._getnet_terminal(provider)
        payload = self._getnet_prepare_transaccion_vals(provider, terminal)
        method = self.env.ref('odoo_pos_getnet_core.payment_method_getnet')
        # sudo: payment.transaction solo tiene ACL para base.group_system
        # en el core; el contador que cobra no la tiene. La transacción la
        # crea la máquina en su nombre (el pago sí es suyo).
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': method.id,
            'reference': 'GETNET-%s-%s' % (self.id, fields.Datetime.now()
                                           .strftime('%Y%m%d%H%M%S')),
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
            'getnet_transaction_origin': 'account_payment',
            'getnet_account_payment_id': self.id,
        })
        self.write({
            'getnet_transaction_id': tx.id,
            'getnet_async_terminal_pending': True,
        })
        self.flush_recordset()
        try:
            data, _req, _resp = provider.getnet_postear_transaccion_con_lock(
                terminal, payload, 'account_payment',
                ref=self.display_name, tx=tx,
                start_worker=lambda d: self._getnet_start_worker_thread(
                    tx, terminal, provider, d))
        except Exception:
            self._getnet_clear_pending()
            raise
        rc = getnet_utils.getnet_rc(data)
        if rc != getnet_utils.GETNET_RC_OK:
            self._getnet_clear_pending()
            tx._set_error(_(
                'Getnet: el posteo fue rechazado (%(rc)s): %(msg)s',
                rc=rc, msg=data.get('Resp_MensajeError') or ''))
            getnet_utils.getnet_safe_commit(self.env)
            raise UserError(_(
                'La terminal Getnet rechazó el posteo (%(rc)s): %(msg)s',
                rc=rc, msg=data.get('Resp_MensajeError') or ''))
        return True

    def _getnet_clear_pending(self):
        self.sudo().write({'getnet_async_terminal_pending': False})
        getnet_utils.getnet_safe_commit(self.env)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _getnet_start_worker_thread(self, tx, terminal, provider, post_data):
        """Lanza el hilo de polling (dentro del try del wrapper del core)."""
        self.ensure_one()
        initial_wait = getnet_utils.getnet_segundos_reconsulta(
            post_data, 5)
        thread = threading.Thread(
            target=self._getnet_worker_thread_entry,
            args=(self.env.cr.dbname, self.env.uid, self.id, tx.id,
                  terminal.id, provider.id, initial_wait),
            daemon=True,
        )
        thread.start()

    @api.model
    def _getnet_worker_thread_entry(self, dbname, uid, payment_id, tx_id,
                                    terminal_id, provider_id, initial_wait):
        """Cuerpo del hilo: cursor propio + worker + liberación en finally."""
        import odoo
        registry = odoo.registry(dbname)
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, uid, {})
            payment = env['account.payment'].browse(payment_id)
            # sudo: el hilo corre con el uid del operador y
            # payment.transaction solo tiene ACL de sistema.
            tx = env['payment.transaction'].sudo().browse(tx_id)
            terminal = env['getnet.pos.terminal'].browse(terminal_id)
            provider = env['payment.provider'].browse(provider_id)
            try:
                payment._getnet_worker_inner(
                    tx, terminal, provider, initial_wait)
            except Exception:
                _logger.exception(
                    'Getnet: fallo en el worker del pago %s; la transacción '
                    'será resuelta por el cron de recuperación.', payment_id)
            finally:
                terminal.getnet_release()
                payment.sudo().write(
                    {'getnet_async_terminal_pending': False})
                getnet_utils.getnet_safe_commit(env)

    def _getnet_worker_inner(self, tx, terminal, provider, initial_wait):
        """
        Lógica del worker, separada del manejo de cursor para poder
        ejecutarla sincrónicamente en tests. NO auto-postea el pago: al
        aprobar queda en borrador y el usuario Confirma.
        """
        self.ensure_one()
        result = tx.getnet_run_query_loop(
            provider, tx.getnet_token, terminal=terminal,
            initial_wait=initial_wait)
        tx.getnet_persist_query_result(result)
        if tx.state == 'done':
            self.message_post(body=_(
                'Cobro aprobado en la terminal Getnet (ticket %(ticket)s, '
                'lote %(lote)s, autorización %(aut)s). Pulse Confirmar '
                'para registrar el pago.',
                ticket=tx.getnet_ticket or '-', lote=tx.getnet_lote or '-',
                aut=tx.getnet_nro_autorizacion or '-'))
        else:
            self.message_post(body=_(
                'La operación en la terminal Getnet no fue aprobada '
                '(estado: %(state)s). %(msg)s',
                state=tx.state, msg=tx.getnet_msg_respuesta or ''))
        self._getnet_bus_notify()
        return result

    def _getnet_bus_notify(self):
        """Notifica al navegador para refrescar el form del pago."""
        self.ensure_one()
        self.env['bus.bus']._sendone(
            'getnet_account_payment_%s' % self.id,
            'getnet_account.payment_refresh',
            {'payment_id': self.id})

    # ------------------------------------------------------------------
    # Bloqueos de post / cancel / draft
    # ------------------------------------------------------------------
    def action_post(self):
        for pay in self:
            if pay.getnet_async_terminal_pending:
                raise UserError(_(
                    'Hay una operación de terminal Getnet en curso para '
                    '%s; espere el resultado antes de confirmar.',
                    pay.display_name))
            if pay._getnet_must_charge_on_terminal():
                raise UserError(_(
                    'El pago %s debe cobrarse en la terminal Getnet antes '
                    'de confirmarse (no hay transacción aprobada).',
                    pay.display_name))
        res = super().action_post()
        self._getnet_reconcile_with_source_invoices()
        return res

    def action_cancel(self):
        for pay in self:
            if pay.getnet_tx_is_done:
                raise UserError(_(
                    'El pago %s tiene un cobro Getnet aprobado en el '
                    'pinpad: no puede cancelarse desde aquí. Realice una '
                    'devolución (DEV) con la transacción original.',
                    pay.display_name))
            if pay.getnet_async_terminal_pending:
                raise UserError(_(
                    'Hay una operación de terminal Getnet en curso para '
                    '%s.', pay.display_name))
        return super().action_cancel()

    def action_draft(self):
        for pay in self:
            if pay.state == 'draft':
                continue
            if pay.getnet_tx_is_done:
                raise UserError(_(
                    'El pago %s tiene un cobro Getnet aprobado: la '
                    'reversión se hace por devolución con ticket, no '
                    'volviendo a borrador.', pay.display_name))
            if pay.getnet_async_terminal_pending:
                raise UserError(_(
                    'Hay una operación de terminal Getnet en curso para '
                    '%s.', pay.display_name))
        return super().action_draft()

    @staticmethod
    def _getnet_open_receivable_lines(record):
        """Apuntes de deudores/acreedores del registro, sin conciliar."""
        return record.line_ids.filtered(
            lambda l: l.account_id.account_type
            in ('asset_receivable', 'liability_payable')
            and not l.reconciled)

    def _getnet_reconcile_with_source_invoices(self):
        """
        Concilia el pago posteado con sus facturas origen.

        Solo se empareja lo que comparte CUENTA: Odoo exige que todas las
        líneas de una conciliación estén en la misma cuenta, y acá el
        costo de equivocarse es alto — este método corre dentro de
        action_post, así que un UserError abortaría la confirmación de un
        cobro YA APROBADO en el pinpad (dinero movido, pago en borrador).
        Por lo mismo el fallo se registra en el chatter y en el log en vez
        de propagarse: la plata ya está cobrada, emparejarla es una tarea
        administrativa que se puede terminar a mano.
        """
        for pay in self:
            if not pay.getnet_source_invoice_ids or pay.state != 'posted':
                continue
            pendientes = pay.env['account.move']
            for move in pay.getnet_source_invoice_ids:
                lines = pay._getnet_open_receivable_lines(pay)
                move_lines = pay._getnet_open_receivable_lines(move)
                propias = lines.filtered(
                    lambda l: l.account_id in move_lines.account_id)
                ajenas = move_lines.filtered(
                    lambda l: l.account_id in propias.account_id)
                if not propias or not ajenas:
                    pendientes |= move
                    continue
                try:
                    (propias + ajenas).reconcile()
                except UserError:
                    _logger.exception(
                        'Getnet: no se pudo conciliar el pago %s con la '
                        'factura %s; queda para conciliación manual.',
                        pay.display_name, move.display_name)
                    pendientes |= move
            if pendientes:
                pay.message_post(body=_(
                    'El cobro Getnet quedó registrado, pero no se pudo '
                    'conciliar automáticamente con %(facturas)s (no hay '
                    'apuntes pendientes en una cuenta común). Concíliela a '
                    'mano desde la factura.',
                    facturas=', '.join(pendientes.mapped('display_name'))))
