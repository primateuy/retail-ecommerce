# -*- coding: utf-8 -*-
"""Hook del cierre de sesión POS: verificación bloqueante + cierre de lote."""

import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _getnet_terminales(self):
        """
        Terminales Getnet de ESTA caja: la que tiene fijada cada método de
        pago del punto de venta.

        Nunca todas las del proveedor. Con varias cajas —una por pinpad,
        que es como se soporta el multi-terminal en el TPV— unir las
        terminales del proveedor haría que al cerrar una caja se cerrara
        el lote de la otra (a mitad de su turno) y que las transacciones
        en vuelo del pinpad ajeno bloquearan este cierre.

        Un método sin terminal fijada solo se resuelve con el mismo atajo
        que usa ``pos.payment.method._getnet_terminal()``: proveedor con
        una sola terminal. Si hay varias, se avisa y se saltea (acá no se
        puede levantar UserError: rompería el cierre de caja).
        """
        self.ensure_one()
        terminales = self.env['getnet.pos.terminal']
        metodos = self.config_id.payment_method_ids.filtered(
            lambda m: m.use_payment_terminal == 'getnet')
        for metodo in metodos:
            if metodo.getnet_terminal_id:
                terminales |= metodo.getnet_terminal_id
                continue
            del_proveedor = metodo.getnet_provider_id.getnet_terminal_ids
            if len(del_proveedor) == 1:
                terminales |= del_proveedor
            else:
                _logger.warning(
                    'Getnet: el método de pago %s del punto de venta %s no '
                    'tiene terminal (TermCod) fijada y su proveedor tiene '
                    '%s: no se verifica ni se cierra su lote al cerrar la '
                    'caja.',
                    metodo.display_name, self.config_id.display_name,
                    len(del_proveedor))
        return terminales

    def action_pos_session_closing_control(self, *args, **kwargs):
        """
        Antes de cerrar la caja: bloquear si hay transacciones Getnet en
        vuelo (el cierre de lote las reversaría) y luego intentar el
        cierre de lote por terminal sin romper el cierre de caja.
        """
        for session in self:
            for terminal in session._getnet_terminales():
                en_vuelo = terminal._getnet_txs_en_vuelo()
                if en_vuelo:
                    raise UserError(_(
                        'No se puede cerrar la caja: la terminal Getnet '
                        '%(term)s tiene %(cant)s transacción(es) en vuelo. '
                        'Espere a que se resuelvan (o un administrador '
                        'puede forzar el cierre de lote desde la '
                        'terminal, con reverso de las pendientes).',
                        term=terminal.display_name, cant=len(en_vuelo)))
        res = super().action_pos_session_closing_control(*args, **kwargs)
        for session in self:
            for terminal in session._getnet_terminales():
                try:
                    terminal.getnet_cerrar_lote(force=False)
                except Exception:
                    # El cierre de lote manda hacerse a diario pero no
                    # debe romper el cierre de caja: se reintenta manual.
                    _logger.exception(
                        'Getnet: fallo el cierre de lote de %s al cerrar '
                        'la sesión %s; ejecutarlo manualmente.',
                        terminal.display_name, session.name)
        return res
