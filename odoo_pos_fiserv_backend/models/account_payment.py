# -*- coding: utf-8 -*-
"""
Integración Fiserv ITD con el pago contable estándar (account.payment).

Desde **contabilidad** el flujo usa solo ``payment.provider`` (Fiserv) ligado a la
**línea de método de pago** del diario: no se resuelve ni se llama a
``pos.payment.method``. Los PosID salen de ``fiserv.pos.terminal`` del mismo proveedor.
El cobro o la devolución van a ITD (processFinancialPurchase / void por ticket + hilo Query);
no interviene sesión de caja ni bus del TPV.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

class AccountPayment(models.Model):
    """
    Extiende account.payment para cobrar o devolver en terminal Fiserv desde contabilidad.

    Flujo **solo backend**: ``payment.provider`` + línea de método del pago; payload y HTTP
    en ``payment.provider`` (sin ``pos.payment.method``). Contabilización al aprobar en ITD.
    """

    _inherit = 'account.payment'

    def write(self, vals):
        """
        Varias instalaciones aplican ``ir.rule`` estrictas por diario sobre ``account.payment``.
        El cliente web suele enviar un ``write`` con **todos** los campos sucios al pulsar
        Confirmar (no sólo flags Fiserv), y ``flush_recordset`` puede volcar otros campos con
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

    fiserv_charge_on_pos = fields.Boolean(
        string='Cobrar en terminal Fiserv (ITD)',
        default=False,
        copy=False,
        help='Si está marcado, al confirmar se envía la operación al pinpad vía ITD, '
        'sin usar el punto de venta ni la sesión de caja.',
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
        help='Terminales PosID del proveedor Fiserv de la línea de método de pago del diario.',
    )
    fiserv_original_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción Fiserv original (devolución)',
        domain=(
            "[('provider_id.code', '=', 'fiserv'), ('ticket_number', '!=', False), "
            "('company_id', '=', company_id), ('state', '=', 'done')]"
        ),
        copy=False,
        help='Cobro Fiserv a anular por ticket; el importe se fija al 100%% del cobro.',
    )
    fiserv_async_terminal_pending = fields.Boolean(
        string='Fiserv: operación lanzada',
        default=False,
        copy=False,
        help='Evita doble confirmación mientras el hilo ITD termina el Query al pinpad.',
    )
    fiserv_source_invoice_ids = fields.Many2many(
        comodel_name='account.move',
        string='Facturas origen (técnico)',
        copy=False,
        help='Facturas asociadas al pago para calcular TaxRefund ITD. '
        'Se llena automáticamente desde el wizard de registro de pago.',
    )
    fiserv_payment_tx_provider_code = fields.Char(
        string='Código proveedor (transacción)',
        compute='_compute_fiserv_payment_tx_provider_code',
        help='Copia en Char del código del proveedor de payment.transaction (provider_id.code '
        'es Selection en Odoo; no puede ser related a Char). Sirve para modifiers en vista.',
    )
    fiserv_is_fiserv_payment_line = fields.Boolean(
        string='Línea de pago Fiserv (técnico)',
        compute='_compute_fiserv_is_fiserv_payment_line',
        help='True cuando el proveedor de la línea de método de pago es Fiserv ITD. '
        'Se usa para condicionar la visibilidad de campos Fiserv en la vista.',
    )
    fiserv_is_integrated_journal = fields.Boolean(
        string='Diario con terminal integrada (técnico)',
        compute='_compute_fiserv_is_integrated_journal',
        help='True si el diario seleccionado tiene alguna línea de método de pago '
        'con proveedor Fiserv. Se usa para mostrar el botón «Crear transacción» '
        'en lugar de «Confirmar» y para auto-marcar «Cobrar en terminal» al elegir '
        'el diario.',
    )
    fiserv_tx_state = fields.Selection(
        related='payment_transaction_id.state',
        string='Estado transacción Fiserv',
        readonly=True,
    )
    fiserv_tx_is_done = fields.Boolean(
        string='Transacción Fiserv aprobada (técnico)',
        compute='_compute_fiserv_tx_is_done',
        help='True cuando hay una transacción Fiserv enlazada y está en estado '
        'done (aprobada por el pinpad). Controla la visibilidad de los botones '
        'Confirmar / Cancelar en el formulario de pago.',
    )
    # Campos unificados para coexistir con odoo_pos_oca_backend: ambos backends
    # heredan la misma vista; si cada uno usa sus propios campos fiserv_/oca_
    # en `position="attributes"`, el último cargado sobrescribe al primero y la
    # UX se rompe. Estos flags cubren ambos lados (via ``_fields`` check).
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
    pos_integrated_draft_blocked = fields.Boolean(
        compute='_compute_pos_integrated_flags',
        help='Oculta el botón «Restablecer a borrador» cuando hay una transacción '
        'POS integrada (Fiserv/OCA) aprobada: un cobro con éxito en pinpad no '
        'puede revertirse desde el form (la anulación se hace por ticket).',
    )

    @api.depends('payment_method_line_id', 'payment_method_line_id.payment_provider_id')
    def _compute_fiserv_is_fiserv_payment_line(self):
        """Detecta si la línea de método de pago seleccionada pertenece a Fiserv."""
        for pay in self:
            provider = pay.payment_method_line_id.payment_provider_id
            pay.fiserv_is_fiserv_payment_line = bool(provider and provider.code == 'fiserv')

    @api.depends(
        'journal_id',
        'journal_id.inbound_payment_method_line_ids.payment_provider_id',
        'journal_id.outbound_payment_method_line_ids.payment_provider_id',
    )
    def _compute_fiserv_is_integrated_journal(self):
        """True si el diario tiene al menos una línea de método de pago Fiserv."""
        for pay in self:
            lines = (
                pay.journal_id.inbound_payment_method_line_ids
                + pay.journal_id.outbound_payment_method_line_ids
            )
            pay.fiserv_is_integrated_journal = any(
                ln.payment_provider_id and ln.payment_provider_id.code == 'fiserv'
                for ln in lines
            )

    @api.depends(
        'payment_transaction_id',
        'payment_transaction_id.state',
        'payment_transaction_id.provider_id',
    )
    def _compute_fiserv_tx_is_done(self):
        """True si hay tx Fiserv enlazada (code='fiserv') y el pinpad la aprobó."""
        for pay in self:
            tx = pay.payment_transaction_id
            is_fiserv_tx = bool(tx and tx.provider_id and tx.provider_id.code == 'fiserv')
            pay.fiserv_tx_is_done = bool(is_fiserv_tx and tx.state == 'done')

    @api.depends(
        'fiserv_async_terminal_pending',
        'fiserv_charge_on_pos',
        'fiserv_tx_is_done',
        'fiserv_is_integrated_journal',
    )
    def _compute_pos_integrated_flags(self):
        """
        Calcula los flags de visibilidad unificados para Fiserv y OCA.

        Mira ambos sets de campos (vía ``_fields``) para que, cuando los dos
        backends coexistan en la misma BD, la UI combine correctamente las
        condiciones aunque Odoo sobreescriba los atributos de la vista.

        ``f_waiting`` también es True si el diario está integrado a Fiserv
        aunque el usuario aún no haya marcado el check «Cobrar en terminal»:
        un diario Fiserv exige pasar por el pinpad sí o sí, no se puede
        Confirmar el pago directo.
        """
        for pay in self:
            f_pending = pay.fiserv_async_terminal_pending
            f_waiting = (
                (pay.fiserv_charge_on_pos or pay.fiserv_is_integrated_journal)
                and not pay.fiserv_tx_is_done
            )
            f_done = pay.fiserv_tx_is_done

            o_pending = o_waiting = o_done = False
            if 'oca_charge_on_pos' in pay._fields:
                o_pending = pay.oca_async_terminal_pending
                o_waiting = pay.oca_charge_on_pos and not pay.oca_tx_is_done
                o_done = pay.oca_tx_is_done

            pay.pos_integrated_post_blocked = f_pending or f_waiting or o_pending or o_waiting
            pay.pos_integrated_cancel_blocked = f_pending or f_done or o_pending or o_done
            pay.pos_integrated_draft_blocked = f_pending or f_done or o_pending or o_done

    @api.depends('payment_transaction_id', 'payment_transaction_id.provider_id')
    def _compute_fiserv_payment_tx_provider_code(self):
        """Expone el código del proveedor de la transacción como texto para la vista."""
        for pay in self:
            tx = pay.payment_transaction_id
            if not tx or not tx.provider_id:
                pay.fiserv_payment_tx_provider_code = False
                continue
            c = tx.provider_id.code
            pay.fiserv_payment_tx_provider_code = c if c not in (False, None) else False

    @api.depends('journal_id', 'company_id', 'payment_method_line_id')
    def _compute_fiserv_terminal_choice_fields(self):
        """
        Lista los terminales Fiserv del proveedor de la línea de método de pago.

        Solo contabilidad: no se consulta ``pos.payment.method`` ni el diario del TPV.
        """
        for pay in self:
            pay.fiserv_selectable_terminal_ids = False
            pay.fiserv_need_terminal_choice = False
            line = pay.payment_method_line_id
            if not line:
                continue
            provider = line.payment_provider_id
            if not provider or provider.code != 'fiserv':
                continue
            terminals = self.env['fiserv.pos.terminal'].search(
                [('payment_provider_id', '=', provider.id)]
            )
            pay.fiserv_selectable_terminal_ids = terminals
            pay.fiserv_need_terminal_choice = len(terminals) > 0

    @api.onchange('fiserv_charge_on_pos', 'journal_id')
    def _onchange_fiserv_charge_on_pos(self):
        """
        Limpia terminal y referencia al desmarcar; si hay un solo PosID, lo preselecciona.
        """
        if not self.fiserv_charge_on_pos:
            self.fiserv_terminal_id = False
            self.fiserv_original_transaction_id = False
            return
        terminals = self.fiserv_selectable_terminal_ids
        if len(terminals) == 1:
            self.fiserv_terminal_id = terminals[0]

    @api.onchange('fiserv_original_transaction_id')
    def _onchange_fiserv_original_transaction_id(self):
        """
        Precarga partner, moneda y monto desde la transacción Fiserv original al
        elegirla. Una devolución por ticket replica al 100%% el cobro original:
        forzar al usuario a re-tipear esos datos solo abre la puerta a errores
        (monto distinto al cobrado → ITD rechaza, partner ajeno → asiento mal
        imputado). El campo ``amount`` queda readonly por modifier de la vista
        para sellar el valor.
        """
        tx = self.fiserv_original_transaction_id
        if not tx:
            return
        if tx.partner_id:
            self.partner_id = tx.partner_id
        if tx.currency_id:
            self.currency_id = tx.currency_id
        if tx.amount:
            self.amount = tx.amount

    @api.onchange('journal_id')
    def _onchange_fiserv_auto_charge_integrated_journal(self):
        """
        Auto-marca «Cobrar en terminal Fiserv» cuando el diario elegido tiene una
        línea de método de pago con proveedor Fiserv. Evita que el usuario tenga
        que tildar manualmente el check cada vez que cambia de diario integrado.
        """
        if self.fiserv_is_integrated_journal and not self.fiserv_charge_on_pos:
            self.fiserv_charge_on_pos = True
            # Preselección del único terminal si aplica (reutiliza el onchange anterior)
            terminals = self.fiserv_selectable_terminal_ids
            if len(terminals) == 1:
                self.fiserv_terminal_id = terminals[0]

    def _fiserv_backend_fiserv_provider(self):
        """
        Proveedor Fiserv ITD para este pago contable (única fuente para envío a ITD).

        Se toma **exclusivamente** de ``payment_method_line_id.payment_provider_id``.
        No se usa ``pos.payment.method`` ni métodos POS del diario.

        Returns:
            payment.provider: proveedor con código ``fiserv``.

        Raises:
            UserError: si falta línea de método o el proveedor no es Fiserv.
        """
        self.ensure_one()
        line = self.payment_method_line_id
        if not line:
            raise UserError(
                _(
                    'Para cobrar con Fiserv ITD desde contabilidad, indique el **método de pago** '
                    '(línea del diario) en este pago.'
                )
            )
        prov = line.payment_provider_id
        if not prov or prov.code != 'fiserv':
            raise UserError(
                _(
                    'Para cobrar con Fiserv ITD desde contabilidad, la línea de método de pago debe '
                    'tener un **proveedor de pago** de tipo Fiserv ITD. Diario «%s», método actual: %s.'
                )
                % (
                    self.journal_id.display_name,
                    line.display_name if line else _('(ninguno)'),
                )
            )
        return prov

    def _fiserv_compute_tax_amount_cents(self):
        """
        Calcula el TaxAmount (IVA real) en centavos para el payload ITD.

        Reglas (petición del cliente):
        - Sin facturas asociadas o más de 1 factura → 0 (exento / no aplica).
        - Exactamente 1 factura → IVA prorrateado por la proporción
          (monto_pago / total_factura) × impuesto_factura.

        Facturas en orden de prioridad:
        1. ``fiserv_source_invoice_ids`` (seleccionadas en el wizard de pago).
        2. ``reconciled_invoice_ids`` (si el pago ya está reconciliado).

        Nota: ``TaxAmount`` es distinto de ``TaxRefund``. ``TaxAmount`` es el
        IVA real de la operación; ``TaxRefund`` es la devolución Ley 17.934.

        Returns:
            str: TaxAmount en centavos (monto × 100) como cadena. ITD espera
            el campo en string.
        """
        self.ensure_one()
        invoices = self.fiserv_source_invoice_ids or self.reconciled_invoice_ids
        if len(invoices) != 1:
            return '0'
        invoice = invoices[0]
        tax_amount = invoice.amount_tax
        if not tax_amount or invoice.amount_total == 0:
            return '0'
        ratio = self.amount / invoice.amount_total
        tax_on_payment = ratio * tax_amount
        return str(int(round(tax_on_payment * 100)))

    def _fiserv_compute_tax_refund_cents(self):
        """
        Calcula el TaxRefund en centavos para el payload ITD.

        Reglas:
        - Sin facturas asociadas o más de 1 factura → 0 (exento).
        - Exactamente 1 factura → (monto_pago / total_factura) × impuesto_factura.

        Las facturas se buscan en orden de prioridad:
        1. fiserv_source_invoice_ids (llenado por el wizard de registro de pago)
        2. reconciled_invoice_ids (si el pago ya está reconciliado)

        Returns:
            int: TaxRefund en centavos (monto × 100).
        """
        self.ensure_one()
        # Buscar facturas asociadas en orden de prioridad
        invoices = self.fiserv_source_invoice_ids or self.reconciled_invoice_ids
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

    def _fiserv_must_run_terminal_before_post(self):
        """
        Indica si debe ejecutarse el terminal antes de super().action_post().

        Returns:
            bool: True si es borrador, tipo soportado, sin tx enlazada y diario Fiserv activo.
        """
        self.ensure_one()
        if not self.fiserv_charge_on_pos:
            return False
        if self.state != 'draft' or self.is_internal_transfer:
            return False
        if self.payment_type not in ('inbound', 'outbound'):
            return False
        if self.payment_transaction_id:
            return False
        if self.fiserv_async_terminal_pending:
            return False
        # --- Si el usuario pidió terminal Fiserv, SIEMPRE intentar flujo ITD.
        #     La validación posterior (_fiserv_validate_before_terminal_charge)
        #     mostrará error claro si falta configuración. Evita "no hace nada". ---
        return True

    def _fiserv_validate_before_terminal_charge(self):
        """
        Validaciones antes de llamar a ITD (contacto, terminal multi-POS, devolución).
        """
        self.ensure_one()
        if not self.fiserv_charge_on_pos:
            return
        prov = self._fiserv_backend_fiserv_provider()
        if not self.partner_id:
            raise UserError(_('Indique el contacto en el pago.'))

        if prov.fiserv_is_multiple and not self.fiserv_terminal_id:
            raise UserError(_('Seleccione el terminal Fiserv (PosID).'))

        if self.payment_type == 'outbound':
            tx_orig = self.fiserv_original_transaction_id
            if not tx_orig:
                raise UserError(
                    _('Indique la transacción Fiserv original a anular por ticket.')
                )
            if not (tx_orig.ticket_number or '').strip():
                raise UserError(_('La transacción original debe tener ticket ITD.'))
            if tx_orig.currency_id != self.currency_id:
                raise UserError(_('La moneda del pago debe coincidir con la transacción original.'))

    def fiserv_send_to_terminal(self):
        """
        Envía cobro o anulación por ticket a ITD (POST inicial).

        Solo **contabilidad**: usa ``payment.provider`` (métodos
        ``fiserv_process_financial_purchase_contable`` / void equivalente). No interviene
        ``pos.payment.method``. El bucle Query corre en hilo compartido (implementación en
        ``pos_payment_method`` como utilitario de modelo); el contexto sigue siendo pago contable.

        Returns:
            dict: Respuesta inicial ITD (ResponseCode '0' = operación enviada al pinpad).

        Raises:
            UserError: tipo de pago no soportado.
        """
        self.ensure_one()
        prov = self._fiserv_backend_fiserv_provider()
        # Backend NO depende de point_of_sale: pasamos sentinels falsy en vez de
        # un recordset vacío de pos.session. Los métodos del provider y el worker
        # ITD aceptan el argumento como opaco y solo lo usan tras chequear truthy.
        empty_pos_session = False
        pos_session_id = False

        if self.payment_type == 'inbound':
            data = prov._prepare_fiserv_itd_payload_for_account_payment(
                self, empty_pos_session
            )
            _logger.info(
                'account.payment Fiserv inbound (solo proveedor / contabilidad): pay=%s prov=%s',
                self.id,
                prov.id,
            )
            return prov.fiserv_process_financial_purchase_contable(
                data, pos_session_id, account_payment_id=self.id
            )

        if self.payment_type == 'outbound':
            tx_orig = self.fiserv_original_transaction_id
            super(AccountPayment, self.sudo()).write({'amount': tx_orig.amount})
            data = prov._prepare_fiserv_itd_void_payload_for_account_payment(
                self, empty_pos_session, tx_orig
            )
            _logger.info(
                'account.payment Fiserv void (solo proveedor / contabilidad): pay=%s prov=%s',
                self.id,
                prov.id,
            )
            return prov.fiserv_process_financial_purchase_void_contable(
                data, pos_session_id, account_payment_id=self.id
            )

        raise UserError(_('Tipo de pago no soportado para terminal Fiserv.'))

    @api.model
    def _fiserv_bus_notify_after_terminal(self, user_id, payment_id, posted, message):
        """
        Notificación + refresco del formulario tras el pinpad (hilo async).

        Odoo no puede devolver ``ir.actions.client`` desde un hilo en segundo plano; el bus
        notifica al navegador con tipo ``fiserv_account.payment_refresh``. El asset backend
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
            _logger.debug('Fiserv: sin partner para bus UI (user=%s)', user_id)
            return
        base = (message or '').strip()
        if posted:
            final_msg = base or _('Pago registrado tras el cobro en terminal.')
        else:
            final_msg = base or _('Revise el pago y el chatter.')
        try:
            self.env['bus.bus'].sudo()._sendone(
                user.partner_id,
                'fiserv_account.payment_refresh',
                {
                    'payment_id': int(payment_id),
                    'posted': bool(posted),
                    'message': final_msg,
                },
            )
        except Exception as err:
            _logger.warning('Fiserv: no se pudo enviar bus de refresco al usuario: %s', err)

    def action_fiserv_create_transaction(self):
        """
        Botón «Crear transacción»: dispara el cobro Fiserv al pinpad **sin postear**.

        Reemplaza a «Confirmar» en el nuevo flujo: primero el usuario crea la
        transacción (pinpad lee la tarjeta, ITD aprueba), y recién después pulsa
        «Confirmar» para registrar contablemente. Permite validar la aprobación
        del terminal antes de contabilizar.

        Al terminar el hilo ITD, el pago queda en ``draft`` con ``payment_transaction_id``
        en ``done`` o ``error`` según resultado; el botón Confirmar se habilita solo
        si quedó ``done``.
        """
        self.ensure_one()
        if self.fiserv_async_terminal_pending:
            raise UserError(
                _(
                    'Ya hay un cobro Fiserv en curso para este pago. Espere el resultado '
                    'en el chatter o en el terminal antes de reintentar.'
                )
            )
        if self.state != 'draft':
            raise UserError(_('Solo se pueden crear transacciones Fiserv sobre pagos en borrador.'))
        if self.payment_transaction_id and self.payment_transaction_id.state == 'done':
            raise UserError(
                _('Este pago ya tiene una transacción Fiserv aprobada. Pulse «Confirmar» para postear.')
            )
        if not self.fiserv_charge_on_pos:
            raise UserError(
                _('Para crear una transacción Fiserv, marque primero «Cobrar en terminal Fiserv».')
            )
        self._fiserv_validate_before_terminal_charge()

        self.sudo().write({'fiserv_async_terminal_pending': True})
        self.sudo().flush_recordset(['fiserv_async_terminal_pending'])

        resp = self.fiserv_send_to_terminal()
        rc = str(resp.get('ResponseCode', '999')).strip()
        if rc != '0':
            self.sudo().write({'fiserv_async_terminal_pending': False})
            self.env.cr.commit()
            raise UserError(
                _('ITD rechazó el inicio: %(c)s — %(m)s')
                % {'c': rc, 'm': resp.get('msg') or ''}
            )
        return True

    def action_draft(self):
        """
        Bloquea «Restablecer a borrador» para pagos con transacción Fiserv aprobada.

        Una vez que el pinpad ITD aprobó la operación, revertir el pago contable
        sin anular la transacción en la red de Fiserv dejaría la base inconsistente
        con la red. La devolución debe hacerse por ticket: nuevo pago outbound
        apuntando a la transacción original (campo ``fiserv_original_transaction_id``).
        """
        blocked = self.filtered(
            lambda p: p.payment_transaction_id
            and p.payment_transaction_id.provider_id.code == 'fiserv'
            and p.payment_transaction_id.state == 'done'
        )
        if blocked:
            raise UserError(
                _(
                    'No se puede restablecer a borrador un pago ya cobrado en '
                    'terminal Fiserv. Para devolver el dinero al cliente, cree un '
                    'pago de tipo «Enviar dinero» y seleccione la transacción '
                    'original en «Devolución con terminal Fiserv».'
                )
            )
        return super().action_draft()

    def action_cancel(self):
        """
        Bloquea «Cancelar» para pagos con transacción Fiserv aprobada (igual lógica
        que ``action_draft``).
        """
        blocked = self.filtered(
            lambda p: p.payment_transaction_id
            and p.payment_transaction_id.provider_id.code == 'fiserv'
            and p.payment_transaction_id.state == 'done'
        )
        if blocked:
            raise UserError(
                _(
                    'No se puede cancelar un pago ya cobrado en terminal Fiserv. '
                    'Para devolver el dinero, cree un pago de tipo «Enviar dinero» '
                    'y seleccione la transacción original.'
                )
            )
        return super().action_cancel()

    def action_post(self):
        """
        Confirmar (postear contablemente). Para pagos con terminal Fiserv, solo
        funciona si ya existe ``payment_transaction_id`` en ``done``; el cobro
        al terminal se dispara previamente con el botón «Crear transacción».

        Pagos sin Fiserv siguen el flujo estándar de ``account.payment``.
        """
        stuck = self.filtered(lambda p: p.fiserv_async_terminal_pending)
        if stuck:
            raise UserError(
                _(
                    'Ya hay un cobro Fiserv en curso para este pago. Espere el resultado '
                    'en el chatter o en el terminal antes de confirmar.'
                )
            )

        fiserv_needs_tx = self.filtered(
            lambda p: p.fiserv_charge_on_pos
            and p.state == 'draft'
            and not p.is_internal_transfer
            and p.payment_type in ('inbound', 'outbound')
            and (not p.payment_transaction_id or p.payment_transaction_id.state != 'done')
        )
        if fiserv_needs_tx:
            raise UserError(
                _(
                    'Debe crear primero la transacción con el botón «Crear transacción» '
                    'y esperar la aprobación del terminal antes de confirmar el pago.'
                )
            )

        # Diario integrado Fiserv sin tx aprobada: forzar el flujo «Crear transacción».
        # Cubre el caso en que el usuario llega al action_post por RPC o por una
        # acción de servidor que evita la UI (los modifiers de la vista no aplican).
        integrated_no_tx = self.filtered(
            lambda p: p.fiserv_is_integrated_journal
            and p.state == 'draft'
            and not p.is_internal_transfer
            and p.payment_type in ('inbound', 'outbound')
            and (not p.payment_transaction_id or p.payment_transaction_id.state != 'done')
        )
        if integrated_no_tx:
            raise UserError(
                _(
                    'El diario seleccionado está integrado a Fiserv. Use el botón '
                    '«Crear transacción» y espere la aprobación del terminal antes '
                    'de confirmar el pago.'
                )
            )

        # Sudo: coherencia con el write (evita reglas que bloquean la confirmación
        # aunque el ACL del modelo sí permita postear).
        res = super(AccountPayment, self.sudo()).action_post()
        # Reconciliación automática con las facturas origen cuando el pago fue
        # disparado desde el nuevo botón «Registrar pago» (que pasa las facturas
        # por contexto). Replica el comportamiento del wizard account.payment.register.
        for pay in self.filtered(lambda p: p.fiserv_source_invoice_ids and p.state == 'posted'):
            pay._fiserv_reconcile_with_source_invoices()
        return res

    def _fiserv_reconcile_with_source_invoices(self):
        """
        Reconcilia las líneas de cobro/pago de este account.payment contra las
        líneas pendientes de las facturas en ``fiserv_source_invoice_ids``.

        Se usa para mantener la UX del wizard estándar cuando el usuario entra
        al form de pago desde el nuevo botón «Registrar pago».
        """
        self.ensure_one()
        invoices = self.fiserv_source_invoice_ids.filtered(lambda m: m.state == 'posted')
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
                        'Fiserv: fallo al reconciliar pago %s con facturas %s: %s',
                        self.id, invoices.ids, exc,
                    )
