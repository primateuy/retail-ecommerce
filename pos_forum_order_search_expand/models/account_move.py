# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        """Habilita reembolsos POS que cruzan empresas.

        Odoo core declara reversed_entry_id con check_company=True
        (account/models/account_move.py). Cuando una devolución se procesa
        en un POS cuya empresa (heredada del journal de la sesión) difiere
        de la empresa de la factura original, la creación del account.move
        aborta con "Empresas incompatibles con los registros".

        Aquí detectamos sólo el caso POS: si el reversed_entry_id apunta a
        una factura vinculada a una pos.order, y la nueva move va a una
        empresa distinta, blanqueamos el puntero. Se pierde la
        reconciliación automática NC↔factura y el botón "Ver reversión" en
        la UI, pero el cierre de sesión POS no se bloquea.

        Para reversiones backend sobre facturas no POS, el check original
        de Odoo sigue activo.
        """
        Journal = self.env['account.journal']
        PosOrder = self.env['pos.order']

        for vals in vals_list:
            reversed_id = vals.get('reversed_entry_id')
            if not reversed_id:
                continue

            # Empresa efectiva del nuevo move: la declarada o la que hereda
            # del journal si company_id no viene explícito.
            nueva_company_id = vals.get('company_id')
            if not nueva_company_id and vals.get('journal_id'):
                nueva_company_id = Journal.browse(vals['journal_id']).company_id.id
            if not nueva_company_id:
                continue

            original = self.browse(reversed_id)
            if not original.company_id or original.company_id.id == nueva_company_id:
                continue

            # Solo intervenimos si la factura original proviene del POS.
            es_factura_pos = PosOrder.sudo().search_count(
                [('account_move', '=', original.id)], limit=1)
            if not es_factura_pos:
                continue

            _logger.info(
                'Reembolso POS cross-empresa detectado: se descarta '
                'reversed_entry_id=%s (empresa %s) porque el nuevo move va '
                'a la empresa %s. La NC queda sin link a la factura original.',
                original.display_name, original.company_id.id, nueva_company_id,
            )
            vals['reversed_entry_id'] = False

        return super().create(vals_list)