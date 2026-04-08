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

    fiserv_charge_on_pos = fields.Boolean(
        string='Cobrar en terminal Fiserv (ITD)',
        default=False,
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
        help='Terminales PosID del proveedor Fiserv de la línea de método de pago del diario.',
    )
    fiserv_original_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción Fiserv original (devolución)',
        domain=(
            "[('provider_id.code', '=', 'fiserv'), ('ticket_number', '!=', False), "
            "('company_id', '=', company_id), ('state', '=', 'done')]"
        ),
        help='Cobro Fiserv a anular por ticket; el importe se fija al 100%% del cobro.',
    )
    fiserv_async_terminal_pending = fields.Boolean(
        string='Fiserv: operación lanzada',
        default=False,
        copy=False,
        help='Evita doble confirmación mientras el hilo ITD termina el Query al pinpad.',
    )
    fiserv_payment_tx_provider_code = fields.Char(
        string='Código proveedor (transacción)',
        compute='_compute_fiserv_payment_tx_provider_code',
        help='Copia en Char del código del proveedor de payment.transaction (provider_id.code '
        'es Selection en Odoo; no puede ser related a Char). Sirve para modifiers en vista.',
    )

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
        empty_pos_session = self.env['pos.session'].browse()
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

    def action_post(self):
        """
        Si aplica Fiserv en terminal, dispara fiserv_send_to_terminal y no contabiliza hasta el hilo.

        El resto de pagos siguen el flujo estándar de account.payment.
        """
        # --- Evitar doble envío mientras ITD está en curso ---
        stuck = self.filtered(lambda p: p.fiserv_async_terminal_pending)
        if stuck:
            raise UserError(
                _(
                    'Ya hay un cobro Fiserv en curso para este pago. Espere el resultado en el chatter '
                    'o en el terminal antes de confirmar de nuevo.'
                )
            )

        fiserv_todo = self.filtered(lambda p: p._fiserv_must_run_terminal_before_post())
        rest = self - fiserv_todo

        for pay in fiserv_todo:
            pay._fiserv_validate_before_terminal_charge()

        # --- Sudo: quien pulse Confirmar puede no tener ACL write o estar bloqueado por reglas;
        #     el flag es sólo técnico (evita doble envío ITD). El ORM ya validó el botón. ---
        for pay in fiserv_todo:
            pay.sudo().write({'fiserv_async_terminal_pending': True})
        # --- Mismo env que el write anterior: si no, el flush puede escribir con uid real. ---
        fiserv_todo.sudo().flush_recordset(['fiserv_async_terminal_pending'])
        #self.env.cr.commit()

        for pay in fiserv_todo:
            resp = pay.fiserv_send_to_terminal()
            rc = str(resp.get('ResponseCode', '999')).strip()
            if rc != '0':
                pay.sudo().write({'fiserv_async_terminal_pending': False})
                pay.env.cr.commit()
                raise UserError(
                    _('ITD rechazó el inicio: %(c)s — %(m)s')
                    % {'c': rc, 'm': resp.get('msg') or ''}
                )

        # --- Contabilizar con sudo en el recordset evita reglas que bloquean líneas/estado
        #     cuando el ACL del modelo sí permite confirmar (mismo criterio que write borrador). ---
        return super(AccountPayment, rest.sudo()).action_post()
