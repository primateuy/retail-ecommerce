# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    envio_cfc_online = fields.Boolean(
        string="Envío CFC online",
        default=False,
        help="Si está activo, al confirmar la orden Odoo intenta firmar el "
             "CFC con UCFE en el momento. Si está inactivo (modo batch, por "
             "defecto), la factura queda pendiente y el cron de "
             "l10n_uy_cfc_efac la envía en su próxima corrida (cada 15 min). "
             "En ambos casos la operativa del cajero NO se interrumpe si "
             "UCFE no está disponible.",
    )

    def _cfc_journal(self):
        """Diario de contingencia del PDV, o un recordset vacío si no lo es.

        Se mira el diario de FACTURAS (`invoice_journal_id`): es el que pone
        `pos.order._prepare_invoice_vals` y el que `l10n_uy_cfc_efac` valida en
        `_post`. `journal_id` es el de los asientos de la sesión, y en Forum son
        distintos en todas las cajas ("Punto de venta" contra "Ventas - SUCURSAL").

        Devuelve el diario en sudo: el cajero no tiene por qué poder leer
        `cae.contingencia` (su ACL es solo contable) y lo necesita para operar.
        """
        self.ensure_one()
        journal = self.sudo().invoice_journal_id
        return journal if journal.es_diario_contingencia else journal.browse()
