# -*- coding: utf-8 -*-
"""
Integración Fiserv ITD con el pago contable estándar (account.payment).

Al elegir un diario con método POS Fiserv, se ofrecen los mismos terminales (PosID)
que en el TPV. El cobro o la devolución se envían directamente a ITD
(processFinancialPurchase / processFinancialPurchaseVoidByTicket + hilo de Query);
no interviene sesión de caja ni canal bus del punto de venta.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    """
    Extiende account.payment para cobrar o devolver en terminal Fiserv desde contabilidad.

    El flujo es autónomo: validación, armado de payload en pos.payment.method, POST a ITD
    y contabilización nativa al cerrar aprobado en el hilo de segundo plano.
    """

    _inherit = 'account.payment'

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
        help='Terminales del proveedor Fiserv vinculado al método POS del diario.',
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

    @api.depends('journal_id', 'company_id')
    def _compute_fiserv_terminal_choice_fields(self):
        """
        Lista los terminales Fiserv del proveedor ligado al método POS del diario.

        Misma fuente de PosID que en el TPV para mantener coherencia de configuración.
        """
        for pay in self:
            # --- Reinicio por registro ---
            pay.fiserv_selectable_terminal_ids = False
            pay.fiserv_need_terminal_choice = False
            pms = pay._fiserv_pos_fiserv_methods()
            pm = pms[:1]
            if not pm or not pm.fiserv_provider_id:
                continue
            # --- Terminales del proveedor payment.provider Fiserv ---
            terminals = self.env['fiserv.pos.terminal'].search(
                [('payment_provider_id', '=', pm.fiserv_provider_id.id)]
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

    def _fiserv_pos_fiserv_methods(self):
        """
        Devuelve métodos POS del diario con terminal Fiserv.

        Returns:
            pos.payment.method: recordset (0 o N) ligado al journal_id.
        """
        self.ensure_one()
        if not self.journal_id:
            return self.env['pos.payment.method']
        return self.env['pos.payment.method'].search(
            [
                ('journal_id', '=', self.journal_id.id),
                ('use_payment_terminal', '=', 'fiserv'),
            ],
        )

    def _fiserv_resolve_pos_payment_method(self):
        """
        Exige exactamente un método POS Fiserv en el diario (regla alineada al TPV).

        Returns:
            pos.payment.method: único registro Fiserv del diario.

        Raises:
            UserError: si no hay método o hay más de uno.
        """
        self.ensure_one()
        pms = self._fiserv_pos_fiserv_methods()
        if not pms:
            raise UserError(
                _('El diario «%s» no tiene método de pago POS con terminal Fiserv ITD.')
                % self.journal_id.display_name
            )
        if len(pms) > 1:
            raise UserError(
                _(
                    'Hay más de un método POS Fiserv en el diario «%s». Debe quedar uno solo.'
                )
                % self.journal_id.display_name
            )
        return pms

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
        return bool(self._fiserv_pos_fiserv_methods())

    def _fiserv_validate_before_terminal_charge(self):
        """
        Validaciones antes de llamar a ITD (contacto, terminal multi-POS, devolución).
        """
        self.ensure_one()
        if not self.fiserv_charge_on_pos:
            return
        pm = self._fiserv_resolve_pos_payment_method()
        if not self.partner_id:
            raise UserError(_('Indique el contacto en el pago.'))

        prov = pm.fiserv_provider_id
        if prov and prov.fiserv_is_multiple:
            if not self.fiserv_terminal_id and not (pm.codigo_terminal or '').strip():
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

        Orquesta el mismo processFinancialPurchase / processFinancialPurchaseVoidByTicket
        que el TPV, pero sin pos_session_id ni bus: el seguimiento Query corre en hilo en
        pos.payment.method y al aprobar se llama action_post en este registro.

        Returns:
            dict: Respuesta inicial ITD (ResponseCode '0' = operación enviada al pinpad).

        Raises:
            UserError: tipo de pago no soportado.
        """
        self.ensure_one()
        pm = self._fiserv_resolve_pos_payment_method()
        # --- Sin sesión POS: payload sólo valida compañía del pago ---
        empty_pos_session = self.env['pos.session'].browse()
        pos_session_id = False

        if self.payment_type == 'inbound':
            data = pm._prepare_fiserv_itd_payload_for_account_payment(
                self, empty_pos_session
            )
            _logger.info(
                'account.payment Fiserv inbound (contabilidad directa): pay=%s pm=%s',
                self.id,
                pm.id,
            )
            return pm.processFinancialPurchase(
                data, pos_session_id, account_payment_id=self.id
            )

        if self.payment_type == 'outbound':
            tx_orig = self.fiserv_original_transaction_id
            self.amount = tx_orig.amount
            data = pm._prepare_fiserv_itd_void_payload_for_account_payment(
                self, empty_pos_session, tx_orig
            )
            _logger.info(
                'account.payment Fiserv void (contabilidad directa): pay=%s pm=%s',
                self.id,
                pm.id,
            )
            return pm.processFinancialPurchaseVoidByTicket(
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

        for pay in fiserv_todo:
            pay.write({'fiserv_async_terminal_pending': True})
        fiserv_todo.flush_recordset(['fiserv_async_terminal_pending'])
        #self.env.cr.commit()

        for pay in fiserv_todo:
            resp = pay.fiserv_send_to_terminal()
            rc = str(resp.get('ResponseCode', '999')).strip()
            if rc != '0':
                pay.write({'fiserv_async_terminal_pending': False})
                pay.env.cr.commit()
                raise UserError(
                    _('ITD rechazó el inicio: %(c)s — %(m)s')
                    % {'c': rc, 'm': resp.get('msg') or ''}
                )

        return super(AccountPayment, rest).action_post()
