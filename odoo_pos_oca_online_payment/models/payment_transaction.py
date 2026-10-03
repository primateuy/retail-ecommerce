# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _process_pos_online_payment(self):
        """Excluye las transacciones del pinpad OCA del flujo de pago online del PDV.

        El cobro con tarjeta ya está en pos.payment; tratarlo como pago online
        agregaría un pago extra a la venta, y como odoo_pos_oca_core no crea el
        account.payment, el estándar termina en ValidationError y la transacción
        se reintenta en cada corrida del cron.
        """
        oca = self.filtered(lambda tx: tx.provider_code == 'oca')
        if oca:
            _logger.debug(
                "OCA: %s transacciones fuera del post-proceso de pago online (%s)",
                len(oca), oca.ids,
            )
        return super(PaymentTransaction, self - oca)._process_pos_online_payment()
