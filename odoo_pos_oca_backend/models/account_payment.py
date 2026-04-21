# -*- coding: utf-8 -*-
"""
Integración OCA POSLink con el pago contable estándar (account.payment). Módulo OCA.

Desde **contabilidad** el flujo usa solo ``payment.provider`` (OCA) ligado a la
**línea de método de pago** del diario: no se resuelve ni se llama a
``pos.payment.method``. Los PosID salen de ``multiple.pos.config`` del mismo proveedor.
El cobro o la devolución van a POSLink (processFinancialPurchase / void por ticket + hilo Query);
no interviene sesión de caja ni bus del TPV.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

class AccountPayment(models.Model):
    """
    Extiende account.payment para cobrar o devolver en terminal OCA desde contabilidad.

    Flujo **solo backend**: ``payment.provider`` + línea de método del pago; payload y HTTP
    en ``payment.provider`` (sin ``pos.payment.method``). Contabilización al aprobar en POSLink.
    """

    _inherit = 'account.payment'

    def write(self, vals):
        """
        Varias instalaciones aplican ``ir.rule`` estrictas por diario sobre ``account.payment``.
        El cliente web suele enviar un ``write`` con **todos** los campos sucios al pulsar
        Confirmar (no sólo flags OCA), y ``flush_recordset`` puede volcar otros campos con
        el uid real: todo eso fallaba con «Access Denied» aunque el usuario tuviera ACL de
        escritura en el modelo.

        Para **borradores** únicamente: si ``check_access_rights('write')`` pasa, el ``write``
        se ejecuta en ``sudo`` y se omiten las reglas de registro. Los **pagos ya registrados**
        siguen el flujo estándar (reglas activas). Quien no tenga ACL de escritura no se eleva.

        Riesgo: quien tenga permiso de escribir pagos en el modelo pero una regla que limitaba
        *qué* borradores podía editar, podrá editar cualquier borrador que pueda abrir/leer.
        En ese caso conviene ajustar la regla o los grupos en lugar de depender de esta ayuda.
        """
        # --- Sin valores: delegar al estándar ---
        if not vals:
            return super().write(vals)
        # --- Sólo borradores: la contabilización (posted) debe respetar reglas habituales ---
        if all(rec.state == 'draft' for rec in self):
            try:
                self.check_access_rights('write')
            except AccessError:
                return super().write(vals)
            return super(AccountPayment, self.sudo()).write(vals)
        return super().write(vals)

    # Redefinir para evitar que al duplicar un pago se copie la transacción original
    payment_transaction_id = fields.Many2one(copy=False)

    oca_charge_on_pos = fields.Boolean(
        string='Cobrar en terminal OCA (POSLink)',
        default=False,
        copy=False,
        help='Si está marcado, al confirmar se envía la operación al pinpad vía POSLink, '
        'sin usar el punto de venta ni la sesión de caja.',
    )
    oca_selectable_pos_ids = fields.Many2many(
        comodel_name='multiple.pos.config',
        compute='_compute_oca_terminal_choice_fields',
        string='Terminales OCA (técnico)',
    )
    oca_need_pos_choice = fields.Boolean(
        string='Requiere elegir terminal',
        compute='_compute_oca_terminal_choice_fields',
    )
    oca_multiple_pos_id = fields.Many2one(
        comodel_name='multiple.pos.config',
        string='Terminal OCA (PosID)',
        domain="[('id', 'in', oca_selectable_pos_ids)]",
        copy=False,
        help='Terminales PosID del proveedor OCA de la línea de método de pago del diario.',
    )
    oca_original_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción OCA original (devolución)',
        domain=(
            "[('provider_id.code', '=', 'oca'), ('ticket_number', '!=', False), "
            "('company_id', '=', company_id), ('state', '=', 'done')]"
        ),
        copy=False,
        help='Cobro OCA a anular por ticket; el importe se fija al 100%% del cobro.',
    )
    oca_async_terminal_pending = fields.Boolean(
        string='OCA: operación lanzada',
        default=False,
        copy=False,
        help='Evita doble confirmación mientras el hilo POSLink termina el Query al pinpad.',
    )
    oca_source_invoice_ids = fields.Many2many(
        comodel_name='account.move',
        relation='account_payment_oca_source_invoice_rel',
        column1='payment_id',
        column2='move_id',
        string='Facturas origen (técnico)',
        copy=False,
        help='Facturas asociadas al pago para calcular TaxRefund POSLink. '
        'Se llena automáticamente desde el wizard de registro de pago.',
    )
    oca_payment_tx_provider_code = fields.Char(
        string='Código proveedor (transacción)',
        compute='_compute_oca_payment_tx_provider_code',
        help='Copia en Char del código del proveedor de payment.transaction (provider_id.code '
        'es Selection en Odoo; no puede ser related a Char). Sirve para modifiers en vista.',
    )
    oca_is_oca_payment_line = fields.Boolean(
        string='Línea de pago OCA (técnico)',
        compute='_compute_oca_is_oca_payment_line',
        help='True cuando el proveedor de la línea de método de pago es OCA POSLink. '
        'Se usa para condicionar la visibilidad de campos OCA en la vista.',
    )
    oca_is_integrated_journal = fields.Boolean(
        string='Diario con terminal integrada (técnico)',
        compute='_compute_oca_is_integrated_journal',
        help='True si el diario seleccionado tiene alguna línea de método de pago '
        'con proveedor OCA. Se usa para mostrar el botón «Crear transacción» '
        'en lugar de «Confirmar» y para auto-marcar «Cobrar en terminal» al elegir '
        'el diario.',
    )
    oca_tx_state = fields.Selection(
        related='payment_transaction_id.state',
        string='Estado transacción OCA',
        readonly=True,
    )
    oca_tx_is_done = fields.Boolean(
        string='Transacción OCA aprobada (técnico)',
        compute='_compute_oca_tx_is_done',
        help='True cuando hay una transacción OCA enlazada y está en estado '
        'done (aprobada por el pinpad). Controla la visibilidad de los botones '
        'Confirmar / Cancelar en el formulario de pago.',
    )
    # Campos unificados para coexistir con odoo_pos_fiserv_backend.
    pos_integrated_post_blocked = fields.Boolean(
        compute='_compute_pos_integrated_flags',
        help='Oculta el botón Confirmar mientras algún backend POS integrado '
        '(Fiserv/OCA) esté esperando aprobación de su terminal.',
    )
    pos_integrated_cancel_blocked = fields.Boolean(
        compute='_compute_pos_integrated_flags',
        help='Oculta el botón Cancelar cuando hay una transacción POS integrada '
        'ya aprobada: se espera el Confirmar, no la cancelación.',
    )

    @api.depends('payment_method_line_id', 'payment_method_line_id.payment_provider_id')
    def _compute_oca_is_oca_payment_line(self):
        """Detecta si la línea de método de pago seleccionada pertenece a OCA."""
        for pay in self:
            provider = pay.payment_method_line_id.payment_provider_id
            pay.oca_is_oca_payment_line = bool(provider and provider.code == 'oca')

    @api.depends(
        'journal_id',
        'journal_id.inbound_payment_method_line_ids.payment_provider_id',
        'journal_id.outbound_payment_method_line_ids.payment_provider_id',
    )
    def _compute_oca_is_integrated_journal(self):
        """True si el diario tiene al menos una línea de método de pago OCA."""
        for pay in self:
            lines = (
                pay.journal_id.inbound_payment_method_line_ids
                + pay.journal_id.outbound_payment_method_line_ids
            )
            pay.oca_is_integrated_journal = any(
                ln.payment_provider_id and ln.payment_provider_id.code == 'oca'
                for ln in lines
            )

    @api.depends(
        'payment_transaction_id',
        'payment_transaction_id.state',
        'payment_transaction_id.provider_id',
    )
    def _compute_oca_tx_is_done(self):
        """True si hay tx OCA enlazada (code='oca') y el pinpad la aprobó."""
        for pay in self:
            tx = pay.payment_transaction_id
            is_oca_tx = bool(tx and tx.provider_id and tx.provider_id.code == 'oca')
            pay.oca_tx_is_done = bool(is_oca_tx and tx.state == 'done')

    @api.depends(
        'oca_async_terminal_pending',
        'oca_charge_on_pos',
        'oca_tx_is_done',
    )
    def _compute_pos_integrated_flags(self):
        """
        Calcula los flags unificados que consumen las vistas de Fiserv y OCA.

        Mira ambos sets (vía ``_fields``) para que la UI sea correcta tanto si
        está solo OCA, solo Fiserv, o los dos instalados (evita que la
        herencia sobrescriba atributos).
        """
        for pay in self:
            o_pending = pay.oca_async_terminal_pending
            o_waiting = pay.oca_charge_on_pos and not pay.oca_tx_is_done
            o_done = pay.oca_tx_is_done

            f_pending = f_waiting = f_done = False
            if 'fiserv_charge_on_pos' in pay._fields:
                f_pending = pay.fiserv_async_terminal_pending
                f_waiting = pay.fiserv_charge_on_pos and not pay.fiserv_tx_is_done
                f_done = pay.fiserv_tx_is_done

            pay.pos_integrated_post_blocked = o_pending or o_waiting or f_pending or f_waiting
            pay.pos_integrated_cancel_blocked = o_pending or o_done or f_pending or f_done

    @api.depends('payment_transaction_id', 'payment_transaction_id.provider_id')
    def _compute_oca_payment_tx_provider_code(self):
        """Expone el código del proveedor de la transacción como texto para la vista."""
        for pay in self:
            tx = pay.payment_transaction_id
            if not tx or not tx.provider_id:
                pay.oca_payment_tx_provider_code = False
                continue
            c = tx.provider_id.code
            pay.oca_payment_tx_provider_code = c if c not in (False, None) else False

    @api.depends('journal_id', 'company_id', 'payment_method_line_id')
    def _compute_oca_terminal_choice_fields(self):
        """
        Lista los terminales OCA del proveedor de la línea de método de pago.

        Solo contabilidad: no se consulta ``pos.payment.method`` ni el diario del TPV.
        """
        for pay in self:
            pay.oca_selectable_pos_ids = False
            pay.oca_need_pos_choice = False
            line = pay.payment_method_line_id
            if not line:
                continue
            provider = line.payment_provider_id
            if not provider or provider.code != 'oca':
                continue
            terminals = self.env['multiple.pos.config'].search(
                [('payment_provider_id', '=', provider.id)]
            )
            pay.oca_selectable_pos_ids = terminals
            pay.oca_need_pos_choice = len(terminals) > 0

    @api.onchange('oca_charge_on_pos', 'journal_id')
    def _onchange_oca_charge_on_pos(self):
        """
        Limpia terminal y referencia al desmarcar; si hay un solo PosID, lo preselecciona.
        """
        if not self.oca_charge_on_pos:
            self.oca_multiple_pos_id = False
            self.oca_original_transaction_id = False
            return
        terminals = self.oca_selectable_pos_ids
        if len(terminals) == 1:
            self.oca_multiple_pos_id = terminals[0]

    @api.onchange('journal_id')
    def _onchange_oca_auto_charge_integrated_journal(self):
        """
        Auto-marca «Cobrar en terminal OCA» cuando el diario elegido tiene una
        línea de método de pago con proveedor OCA. Evita que el usuario tenga
        que tildar manualmente el check cada vez que cambia de diario integrado.
        """
        if self.oca_is_integrated_journal and not self.oca_charge_on_pos:
            self.oca_charge_on_pos = True
            # Preselección del único terminal si aplica (reutiliza el onchange anterior)
            terminals = self.oca_selectable_pos_ids
            if len(terminals) == 1:
                self.oca_multiple_pos_id = terminals[0]

    def _oca_backend_provider(self):
        """
        Proveedor OCA POSLink para este pago contable (única fuente para envío a POSLink).

        Se toma **exclusivamente** de ``payment_method_line_id.payment_provider_id``.
        No se usa ``pos.payment.method`` ni métodos POS del diario.

        Returns:
            payment.provider: proveedor con código ``oca``.

        Raises:
            UserError: si falta línea de método o el proveedor no es OCA.
        """
        self.ensure_one()
        line = self.payment_method_line_id
        if not line:
            raise UserError(
                _(
                    'Para cobrar con OCA POSLink desde contabilidad, indique el **método de pago** '
                    '(línea del diario) en este pago.'
                )
            )
        prov = line.payment_provider_id
        if not prov or prov.code != 'oca':
            raise UserError(
                _(
                    'Para cobrar con OCA POSLink desde contabilidad, la línea de método de pago debe '
                    'tener un **proveedor de pago** de tipo OCA POSLink. Diario «%s», método actual: %s.'
                )
                % (
                    self.journal_id.display_name,
                    line.display_name if line else _('(ninguno)'),
                )
            )
        return prov

    def _oca_compute_tax_amount_cents(self):
        """
        Calcula el TaxAmount (IVA real) en centavos para el payload POSLink.

        Reglas (petición del cliente):
        - Sin facturas asociadas o más de 1 factura → 0 (exento / no aplica).
        - Exactamente 1 factura → IVA prorrateado por la proporción
          (monto_pago / total_factura) × impuesto_factura.

        Facturas en orden de prioridad:
        1. ``oca_source_invoice_ids`` (seleccionadas en el wizard de pago).
        2. ``reconciled_invoice_ids`` (si el pago ya está reconciliado).

        Nota: ``TaxAmount`` es distinto de ``TaxRefund``. ``TaxAmount`` es el
        IVA real de la operación; ``TaxRefund`` es la devolución Ley 17.934.

        Returns:
            str: TaxAmount en centavos (monto × 100) como cadena. POSLink
            espera el campo en string.
        """
        self.ensure_one()
        invoices = self.oca_source_invoice_ids or self.reconciled_invoice_ids
        if len(invoices) != 1:
            return '0'
        invoice = invoices[0]
        tax_amount = invoice.amount_tax
        if not tax_amount or invoice.amount_total == 0:
            return '0'
        ratio = self.amount / invoice.amount_total
        tax_on_payment = ratio * tax_amount
        return str(int(round(tax_on_payment * 100)))

    def _oca_compute_tax_refund_cents(self):
        """
        Calcula el TaxRefund en centavos para el payload POSLink.

        Reglas:
        - Sin facturas asociadas o más de 1 factura → 0 (exento).
        - Exactamente 1 factura → (monto_pago / total_factura) × impuesto_factura.

        Las facturas se buscan en orden de prioridad:
        1. oca_source_invoice_ids (llenado por el wizard de registro de pago)
        2. reconciled_invoice_ids (si el pago ya está reconciliado)

        Returns:
            int: TaxRefund en centavos (monto × 100).
        """
        self.ensure_one()
        # Buscar facturas asociadas en orden de prioridad
        invoices = self.oca_source_invoice_ids or self.reconciled_invoice_ids
        if len(invoices) != 1:
            return 0
        invoice = invoices[0]
        # Monto total de impuestos de la factura
        tax_amount = invoice.amount_tax
        if not tax_amount or invoice.amount_total == 0:
            return 0
        # Proporción: (monto del pago / total de la factura) × impuesto de la factura
        ratio = self.amount / invoice.amount_total
        tax_refund = ratio * tax_amount
        return int(round(tax_refund * 100))

    def _oca_must_run_terminal_before_post(self):
        """
        Indica si debe ejecutarse el terminal antes de super().action_post().

        Returns:
            bool: True si es borrador, tipo soportado, sin tx enlazada y diario OCA activo.
        """
        self.ensure_one()
        if not self.oca_charge_on_pos:
            return False
        if self.state != 'draft' or self.is_internal_transfer:
            return False
        if self.payment_type not in ('inbound', 'outbound'):
            return False
        if self.payment_transaction_id:
            return False
        if self.oca_async_terminal_pending:
            return False
        # --- Si el usuario pidió terminal OCA, SIEMPRE intentar flujo POSLink.
        #     La validación posterior (_oca_validate_before_terminal_charge)
        #     mostrará error claro si falta configuración. Evita "no hace nada". ---
        return True

    def _oca_validate_before_terminal_charge(self):
        """
        Validaciones antes de llamar a POSLink (contacto, terminal multi-POS, devolución).
        """
        self.ensure_one()
        if not self.oca_charge_on_pos:
            return
        prov = self._oca_backend_provider()
        if not self.partner_id:
            raise UserError(_('Indique el contacto en el pago.'))

        if prov.is_multiple and not self.oca_multiple_pos_id:
            raise UserError(_('Seleccione el terminal OCA (PosID).'))

        if self.payment_type == 'outbound':
            tx_orig = self.oca_original_transaction_id
            if not tx_orig:
                raise UserError(
                    _('Indique la transacción OCA original a anular por ticket.')
                )
            if not (tx_orig.ticket_number or '').strip():
                raise UserError(_('La transacción original debe tener ticket POSLink.'))
            if tx_orig.currency_id != self.currency_id:
                raise UserError(_('La moneda del pago debe coincidir con la transacción original.'))

    def oca_send_to_terminal(self):
        """
        Envía cobro o anulación por ticket a POSLink (POST inicial).

        Solo **contabilidad**: usa ``payment.provider`` (métodos
        ``oca_process_financial_purchase_contable`` / void equivalente). No interviene
        ``pos.payment.method``. El bucle Query corre en hilo compartido (implementación en
        ``pos_payment_method`` como utilitario de modelo); el contexto sigue siendo pago contable.

        Returns:
            dict: Respuesta inicial POSLink (ResponseCode '0' = operación enviada al pinpad).

        Raises:
            UserError: tipo de pago no soportado.
        """
        self.ensure_one()
        prov = self._oca_backend_provider()
        empty_pos_session = self.env['pos.session'].browse()
        pos_session_id = False

        if self.payment_type == 'inbound':
            data = prov._prepare_oca_pos_payload_for_account_payment(
                self, empty_pos_session
            )
            _logger.info(
                'account.payment OCA inbound (solo proveedor / contabilidad): pay=%s prov=%s',
                self.id,
                prov.id,
            )
            return prov.oca_process_financial_purchase_contable(
                data, pos_session_id, account_payment_id=self.id
            )

        if self.payment_type == 'outbound':
            tx_orig = self.oca_original_transaction_id
            super(AccountPayment, self.sudo()).write({'amount': tx_orig.amount})
            data = prov._prepare_oca_pos_void_payload_for_account_payment(
                self, empty_pos_session, tx_orig
            )
            _logger.info(
                'account.payment OCA void (solo proveedor / contabilidad): pay=%s prov=%s',
                self.id,
                prov.id,
            )
            return prov.oca_process_financial_purchase_void_contable(
                data, pos_session_id, account_payment_id=self.id
            )

        raise UserError(_('Tipo de pago no soportado para terminal OCA.'))

    @api.model
    def _oca_bus_notify_after_terminal(self, user_id, payment_id, posted, message):
        """
        Notificación + refresco del formulario tras el pinpad (hilo async).

        Odoo no puede devolver ``ir.actions.client`` desde un hilo en segundo plano; el bus
        notifica al navegador con tipo ``oca_account.payment_refresh``. El asset backend
        usa ``action.restore`` / ``soft_reload`` (acciones cliente estándar del módulo web).

        Args:
            user_id (int): Usuario que pulsó Confirmar (run_uid del hilo).
            payment_id (int): ID del account.payment (para recargar solo si el formulario coincide).
            posted (bool): True si action_post nativo terminó bien.
            message (str): Texto ya traducido para el toast.
        """
        if not user_id or not payment_id:
            return
        user = self.env['res.users'].sudo().browse(int(user_id))
        if not user.exists() or not user.partner_id:
            _logger.debug('OCA: sin partner para bus UI (user=%s)', user_id)
            return
        base = (message or '').strip()
        if posted:
            final_msg = base or _('Pago registrado tras el cobro en terminal.')
        else:
            final_msg = base or _('Revise el pago y el chatter.')
        try:
            self.env['bus.bus'].sudo()._sendone(
                user.partner_id,
                'oca_account.payment_refresh',
                {
                    'payment_id': int(payment_id),
                    'posted': bool(posted),
                    'message': final_msg,
                },
            )
        except Exception as err:
            _logger.warning('OCA: no se pudo enviar bus de refresco al usuario: %s', err)

    def action_oca_create_transaction(self):
        """
        Botón «Crear transacción»: dispara el cobro OCA al pinpad **sin postear**.

        Reemplaza a «Confirmar» en el nuevo flujo: primero el usuario crea la
        transacción (pinpad lee la tarjeta, POSLink aprueba), y recién después pulsa
        «Confirmar» para registrar contablemente. Permite validar la aprobación
        del terminal antes de contabilizar.

        Al terminar el hilo POSLink, el pago queda en ``draft`` con ``payment_transaction_id``
        en ``done`` o ``error`` según resultado; el botón Confirmar se habilita solo
        si quedó ``done``.
        """
        self.ensure_one()
        if self.oca_async_terminal_pending:
            raise UserError(
                _(
                    'Ya hay un cobro OCA en curso para este pago. Espere el resultado '
                    'en el chatter o en el terminal antes de reintentar.'
                )
            )
        if self.state != 'draft':
            raise UserError(_('Solo se pueden crear transacciones OCA sobre pagos en borrador.'))
        if self.payment_transaction_id and self.payment_transaction_id.state == 'done':
            raise UserError(
                _('Este pago ya tiene una transacción OCA aprobada. Pulse «Confirmar» para postear.')
            )
        if not self.oca_charge_on_pos:
            raise UserError(
                _('Para crear una transacción OCA, marque primero «Cobrar en terminal OCA».')
            )
        self._oca_validate_before_terminal_charge()

        self.sudo().write({'oca_async_terminal_pending': True})
        self.sudo().flush_recordset(['oca_async_terminal_pending'])

        resp = self.oca_send_to_terminal()
        rc = str(resp.get('ResponseCode', '999')).strip()
        if rc != '0':
            self.sudo().write({'oca_async_terminal_pending': False})
            self.env.cr.commit()
            raise UserError(
                _('POSLink rechazó el inicio: %(c)s — %(m)s')
                % {'c': rc, 'm': resp.get('msg') or ''}
            )
        return True

    def action_post(self):
        """
        Confirmar (postear contablemente). Para pagos con terminal OCA, solo
        funciona si ya existe ``payment_transaction_id`` en ``done``; el cobro
        al terminal se dispara previamente con el botón «Crear transacción».

        Pagos sin OCA siguen el flujo estándar de ``account.payment``.
        """
        stuck = self.filtered(lambda p: p.oca_async_terminal_pending)
        if stuck:
            raise UserError(
                _(
                    'Ya hay un cobro OCA en curso para este pago. Espere el resultado '
                    'en el chatter o en el terminal antes de confirmar.'
                )
            )

        oca_needs_tx = self.filtered(
            lambda p: p.oca_charge_on_pos
            and p.state == 'draft'
            and not p.is_internal_transfer
            and p.payment_type in ('inbound', 'outbound')
            and (not p.payment_transaction_id or p.payment_transaction_id.state != 'done')
        )
        if oca_needs_tx:
            raise UserError(
                _(
                    'Debe crear primero la transacción con el botón «Crear transacción» '
                    'y esperar la aprobación del terminal antes de confirmar el pago.'
                )
            )

        # Sudo: coherencia con el write (evita reglas que bloquean la confirmación
        # aunque el ACL del modelo sí permita postear).
        res = super(AccountPayment, self.sudo()).action_post()
        # Reconciliación automática con las facturas origen cuando el pago fue
        # disparado desde el nuevo botón «Registrar pago» (que pasa las facturas
        # por contexto). Replica el comportamiento del wizard account.payment.register.
        for pay in self.filtered(lambda p: p.oca_source_invoice_ids and p.state == 'posted'):
            pay._oca_reconcile_with_source_invoices()
        return res

    def _oca_reconcile_with_source_invoices(self):
        """
        Reconcilia las líneas de cobro/pago de este account.payment contra las
        líneas pendientes de las facturas en ``oca_source_invoice_ids``.

        Se usa para mantener la UX del wizard estándar cuando el usuario entra
        al form de pago desde el nuevo botón «Registrar pago».
        """
        self.ensure_one()
        invoices = self.oca_source_invoice_ids.filtered(lambda m: m.state == 'posted')
        if not invoices:
            return
        payment_lines = self.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
            and not l.reconciled
        )
        invoice_lines = invoices.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
            and not l.reconciled
        )
        if not payment_lines or not invoice_lines:
            return
        # Reconciliar solo si comparten cuenta (misma contabilidad receivable/payable).
        for account in payment_lines.mapped('account_id'):
            to_rec = (payment_lines + invoice_lines).filtered(
                lambda l: l.account_id == account
            )
            if len(to_rec) >= 2:
                try:
                    to_rec.reconcile()
                except Exception as exc:
                    _logger.warning(
                        'OCA: fallo al reconciliar pago %s con facturas %s: %s',
                        self.id, invoices.ids, exc,
                    )
