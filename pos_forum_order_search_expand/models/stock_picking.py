# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _link_owner_on_return_picking(self, lines):
        """Permite devolver una orden hecha en otra sucursal.

        Es el punto exacto donde reventaba la validación de la devolución:
        core hace `lines[0].order_id.refunded_order_ids.picking_ids` para
        recuperar el propietario del artículo devuelto, y ahí lee la orden
        original, que el cajero no tiene permitido leer (ver el detalle en
        `pos_order.py`).

        Se hace sudo() sobre las líneas, no sobre el picking: el movimiento
        de stock se sigue creando con los permisos del cajero.
        """
        return super()._link_owner_on_return_picking(lines.sudo())
