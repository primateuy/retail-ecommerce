# -*- coding: utf-8 -*-
"""
Módulo para limpiar sesiones de POS eliminando pos.order en borrador
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    """
    Extensión del modelo pos.session para agregar funcionalidad de limpieza
    de sesión al cerrar, eliminando pos.order en borrador
    """
    _inherit = 'pos.session'

    def _cleanup_draft_pos_orders(self):
        """
        Elimina las pos.order en borrador asociadas a esta sesión
        """
        for session in self:
            # Buscar pos.order en borrador asociadas a esta sesión
            draft_pos_orders = self.env['pos.order'].search([
                ('session_id', '=', session.id),
                ('state', 'in', ['draft', 'cancel'])
            ])
            
            if draft_pos_orders:
                _logger.info(f"Eliminando {len(draft_pos_orders)} pos.order en borrador de sesión {session.name}")
                
                # Eliminar cada pos.order en borrador
                for pos_order in draft_pos_orders:
                    # Eliminar primero los pagos asociados
                    if pos_order.payment_ids:
                        pos_order.payment_ids.unlink()
                    
                    # Eliminar las líneas de la orden
                    if pos_order.lines:
                        pos_order.lines.unlink()
                    
                    # Eliminar la pos.order en borrador
                    pos_order.unlink()
                
                _logger.info(f"Se eliminaron {len(draft_pos_orders)} pos.order de la sesión {session.name}")

    def action_pos_session_closing_control(self):
        """
        Sobrescribe el método de cierre de sesión para limpiar pos.order en borrador
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self).action_pos_session_closing_control()

    def action_pos_session_close(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """
        Sobrescribe el método de cierre de sesión para limpiar pos.order en borrador
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self).action_pos_session_close(balancing_account, amount_to_balance, bank_payment_method_diffs)

    def action_pos_session_validate(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """
        Sobrescribe el método de validación de sesión para limpiar pos.order en borrador
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self).action_pos_session_validate(balancing_account, amount_to_balance, bank_payment_method_diffs)

    def _cannot_close_session(self, bank_payment_method_diffs=None):
        """
        Sobrescribe el método que verifica si se puede cerrar la sesión
        para limpiar pos.order en borrador antes de la verificación
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self)._cannot_close_session(bank_payment_method_diffs)

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """
        Sobrescribe el método de validación de sesión para limpiar pos.order en borrador
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self)._validate_session(balancing_account, amount_to_balance, bank_payment_method_diffs)

    def _check_pos_session_balance(self):
        """
        Sobrescribe el método de verificación de balance para permitir cierre
        cuando hay pos.order en borrador (después de limpiarlas)
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self)._check_pos_session_balance()

    def _check_orders_not_invoiced(self):
        """
        Sobrescribe el método que verifica órdenes no facturadas para permitir cierre
        cuando hay pos.order en borrador (después de limpiarlas)
        """
        self._cleanup_draft_pos_orders()
        return super(PosSession, self)._check_orders_not_invoiced()

    def manual_cleanup_documents(self):
        """
        Método para limpieza manual de pos.order en borrador
        """
        for session in self:
            session._cleanup_draft_pos_orders()
            
            # Mostrar notificación
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Limpieza Completada'),
                    'message': _('Se han eliminado las pos.order en borrador de la sesión.'),
                    'type': 'success',
                    'sticky': False,
                }
            } 