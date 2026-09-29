# -*- coding: utf-8 -*-

from odoo import api, models
import logging
_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _payment_fields(self, order, ui_paymentline):
        """Guarda los datos del cheque AL CREAR el pago.

        🔴 Antes se escribían después de `create_from_ui`, emparejando cheques y
        pagos por orden. Si algo fallaba al final de la venta —la emisión del
        CFE, por ejemplo, que ocurre después de guardar la orden—, ese paso no
        se ejecutaba y el pago quedaba sin los datos: al cerrar la caja no se
        creaba el cheque, sin ningún aviso. Acá cada línea de pago del PDV lleva
        sus propios datos, en el mismo momento en que se crea el pos.payment.
        """
        vals = super()._payment_fields(order, ui_paymentline)
        check_number = (ui_paymentline.get('check_number') or '').strip()
        if check_number:
            bank_name = ui_paymentline.get('bank_name')
            try:
                # El banco es opcional: sin él, `int(None)` hacía fallar todo.
                bank_id = int(bank_name) if bank_name else False
            except (TypeError, ValueError):
                bank_id = False
            vals.update({
                'check_number': check_number,
                'check_owner': ui_paymentline.get('owner_name') or False,
                'check_bank_account': ui_paymentline.get('bank_account') or False,
                'bank_id': bank_id,
            })
        return vals
